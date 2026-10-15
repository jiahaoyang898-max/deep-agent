# [认证微服务] 独立登录注册服务（不改动原后端任何代码）
# - SQLite 存储，零外部依赖
# - PBKDF2-SHA256 加盐哈希，绝不存明文
# - Bearer Token 认证
import os
import sqlite3
import secrets
import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("AUTH_DB_PATH", "/data/auth.db"))
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 天
MIN_PWD_LEN = 6
MIN_NAME_LEN = 2


def parse_cors_origins(raw: str | None) -> list[str]:
    """解析 CORS_ALLOW_ORIGINS 环境变量（逗号分隔）。

    - 未设置（None）或为空 / 全为空白 → 回退 ["*"]（保持历史行为）
    - 多个逗号分隔值 → 去空白后返回列表
    """
    if raw is None:
        return ["*"]
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or ["*"]


CORS_ALLOW_ORIGINS = parse_cors_origins(os.getenv("CORS_ALLOW_ORIGINS"))

app = FastAPI(title="DeepAgent Auth", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 登录/注册失败限流（进程内滑动窗口）----------
# 目的：登录页带演示账号（弱口令），若无失败限制可被暴力破解。
# 策略：只对「失败」计数，同 IP 在窗口内失败达到上限即拒绝；一旦成功立即清零，
#       因此正常用户不会被误伤。
# 说明：单进程内存实现，够用且零外部依赖；若将来多 worker / 多副本部署，
#       把 _rate_failures 换成 Redis（key = ip，ZSET 存时间戳）即可，接口不用变。
RATE_WINDOW_SECONDS = 300  # 滑动窗口：5 分钟
# 双闸门设计（务必成对保留）：
#   ① 按「IP + 用户名」限流 —— 保护单个账号不被猜密码，也是主要的暴力破解防线；
#   ② 按「IP」总额限流 —— 防止攻击者换用户名来绕过 ① 反复刷接口。
# 之所以不只用 IP：Nginx 用 `proxy_set_header X-Real-IP $remote_addr` 覆盖客户端伪造值
# （防伪造，必须保留），但在 Docker Desktop 之类的端口映射下 $remote_addr 会收敛成
# 同一个网关地址，只用 IP 会让「一个人失败 10 次 = 所有人被锁」。加 ① 后各账号互不牵连。
RATE_MAX_FAILURES_PER_ACCOUNT = 10
RATE_MAX_FAILURES_PER_IP = 60
RATE_MAX_TRACKED_KEYS = 20_000  # 防止被海量伪造 key 撑爆内存

_rate_lock = threading.Lock()
_rate_failures: "defaultdict[str, deque[float]]" = defaultdict(deque)


def client_ip(request: Request) -> str:
    """取真实客户端 IP。

    经 Nginx 网关访问时 ``request.client.host`` 是网关地址（127.0.0.1），
    所以优先取反代注入的头：X-Real-IP → X-Forwarded-For 首段 → 回落 socket 地址。
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _drop_expired(bucket: "deque[float]", now: float) -> None:
    """丢弃窗口外的旧时间戳（deque 里时间戳单调递增，从头弹即可）。"""
    while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
        bucket.popleft()


def _acct_key(ip: str, username: str) -> str:
    """「IP + 用户名」桶的 key。用户名截断，避免超长串撑内存。"""
    return f"acct:{ip}|{(username or '').strip()[:64]}"


def _ip_key(ip: str) -> str:
    return f"ip:{ip}"


def _consume(key: str, limit: int, now: float) -> None:
    """窗口内失败次数已达 limit → 抛 429（带 Retry-After）。调用方需持有 _rate_lock。"""
    bucket = _rate_failures.get(key)  # 用 get 而非 defaultdict，避免成功请求也建桶
    if not bucket:
        return
    _drop_expired(bucket, now)
    if len(bucket) >= limit:
        retry_after = max(1, int(RATE_WINDOW_SECONDS - (now - bucket[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"失败次数过多，请 {retry_after} 秒后再试",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit_guard(request: Request, username: str) -> str:
    """前置检查：任一闸门超限即 429。返回客户端 IP 供后续记录使用。

    用户名只用于分桶，不写日志、不回显进响应体。
    """
    ip = client_ip(request)
    now = time.time()
    with _rate_lock:
        _consume(_acct_key(ip, username), RATE_MAX_FAILURES_PER_ACCOUNT, now)
        _consume(_ip_key(ip), RATE_MAX_FAILURES_PER_IP, now)
    return ip


def record_failure(ip: str, username: str) -> None:
    """记一次失败：两个闸门同时 +1。只存时间戳，绝不记录用户名/密码等敏感内容。"""
    now = time.time()
    with _rate_lock:
        if len(_rate_failures) > RATE_MAX_TRACKED_KEYS:
            # 先回收空桶，仍超量则整体清空，避免内存无限增长。
            for empty in [k for k, v in _rate_failures.items() if not v]:
                del _rate_failures[empty]
            if len(_rate_failures) > RATE_MAX_TRACKED_KEYS:
                _rate_failures.clear()
        for key in (_acct_key(ip, username), _ip_key(ip)):
            bucket = _rate_failures[key]
            _drop_expired(bucket, now)
            bucket.append(now)


def clear_failures(ip: str, username: str) -> None:
    """认证成功 → 只清零该「IP + 用户名」的计数；IP 总闸靠自然衰减，不可被成功请求重置。"""
    with _rate_lock:
        _rate_failures.pop(_acct_key(ip, username), None)


# ---------- 数据库 ----------
def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout: 并发写时等锁而不是立刻抛 "database is locked"
    # WAL: 读写不互相阻塞，配合 timeout 才能撑住并发登录
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                pwd_hash      TEXT NOT NULL,
                salt          TEXT NOT NULL,
                created_at    TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS tokens (
                token       TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                expires_at  REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


# ---------- 密码哈希 ----------
def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()


def verify_password(password: str, salt: str, expected: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt), expected)


# ---------- 模型 ----------
class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)


class VerifyRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


# ---------- 依赖 ----------
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer(auto_error=False)


def _resolve_token(token: str) -> dict:
    """校验 token 并返回用户；无效/过期抛 401。backend 跨服务鉴权走这里。"""
    with db() as conn:
        row = conn.execute(
            """SELECT t.token, t.expires_at, u.id, u.username
               FROM tokens t JOIN users u ON u.id = t.user_id
               WHERE t.token = ?""",
            (token,),
        ).fetchone()
    if row is None or row["expires_at"] < time.time():
        raise HTTPException(401, "登录已过期，请重新登录")
    return {"user_id": row["id"], "username": row["username"]}


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "未提供认证凭证")
    return _resolve_token(cred.credentials)


# ---------- 接口 ----------
@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/register")
def register(body: Credentials, request: Request):
    name = body.username.strip()
    ip = rate_limit_guard(request, name)
    if len(name) < MIN_NAME_LEN:
        record_failure(ip, name)
        raise HTTPException(400, f"用户名至少 {MIN_NAME_LEN} 个字符")
    if len(body.password) < MIN_PWD_LEN:
        record_failure(ip, name)
        raise HTTPException(400, f"密码至少 {MIN_PWD_LEN} 位")

    salt = secrets.token_hex(16)
    pwd_hash = hash_password(body.password, salt)

    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, pwd_hash, salt) VALUES (?, ?, ?)",
                (name, pwd_hash, salt),
            )
        except sqlite3.IntegrityError:
            record_failure(ip, name)
            raise HTTPException(400, "该用户名已被注册，换一个试试")

        token = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, cur.lastrowid, time.time() + TOKEN_TTL_SECONDS),
        )
    clear_failures(ip, name)
    return {"token": token, "username": name}


@app.post("/api/auth/login")
def login(body: Credentials, request: Request):
    name = body.username.strip()
    ip = rate_limit_guard(request, name)
    with db() as conn:
        user = conn.execute(
            "SELECT id, username, pwd_hash, salt FROM users WHERE username = ?",
            (name,),
        ).fetchone()
    if user is None or not verify_password(body.password, user["salt"], user["pwd_hash"]):
        record_failure(ip, name)
        raise HTTPException(401, "用户名或密码错误")

    token = secrets.token_hex(32)
    with db() as conn:
        conn.execute(
            "INSERT INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user["id"], time.time() + TOKEN_TTL_SECONDS),
        )
    clear_failures(ip, name)
    return {"token": token, "username": user["username"]}


@app.post("/api/auth/logout")
def logout(user=Depends(current_user), cred: HTTPAuthorizationCredentials = Depends(bearer)):
    with db() as conn:
        conn.execute("DELETE FROM tokens WHERE token = ?", (cred.credentials,))
    return {"status": "logged_out"}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"username": user["username"]}


@app.post("/api/auth/verify")
def verify(body: VerifyRequest):
    """供 backend 跨服务校验令牌（两个容器文件系统隔离，不能共享 SQLite）。"""
    return _resolve_token(body.token)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
