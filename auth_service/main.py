# [认证微服务] 独立登录注册服务（不改动原后端任何代码）
# - SQLite 存储，零外部依赖
# - PBKDF2-SHA256 加盐哈希，绝不存明文
# - Bearer Token 认证
import os
import sqlite3
import secrets
import hashlib
import hmac
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends
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


# ---------- 数据库 ----------
def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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


# ---------- 依赖 ----------
import time

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "未提供认证凭证")
    with db() as conn:
        row = conn.execute(
            """SELECT t.token, t.expires_at, u.id, u.username
               FROM tokens t JOIN users u ON u.id = t.user_id
               WHERE t.token = ?""",
            (cred.credentials,),
        ).fetchone()
    if row is None or row["expires_at"] < time.time():
        raise HTTPException(401, "登录已过期，请重新登录")
    return {"user_id": row["id"], "username": row["username"]}


# ---------- 接口 ----------
@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/register")
def register(body: Credentials):
    name = body.username.strip()
    if len(name) < MIN_NAME_LEN:
        raise HTTPException(400, f"用户名至少 {MIN_NAME_LEN} 个字符")
    if len(body.password) < MIN_PWD_LEN:
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
            raise HTTPException(400, "该用户名已被注册，换一个试试")

        token = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, cur.lastrowid, time.time() + TOKEN_TTL_SECONDS),
        )
    return {"token": token, "username": name}


@app.post("/api/auth/login")
def login(body: Credentials):
    with db() as conn:
        user = conn.execute(
            "SELECT id, username, pwd_hash, salt FROM users WHERE username = ?",
            (body.username.strip(),),
        ).fetchone()
    if user is None or not verify_password(body.password, user["salt"], user["pwd_hash"]):
        raise HTTPException(401, "用户名或密码错误")

    token = secrets.token_hex(32)
    with db() as conn:
        conn.execute(
            "INSERT INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user["id"], time.time() + TOKEN_TTL_SECONDS),
        )
    return {"token": token, "username": user["username"]}


@app.post("/api/auth/logout")
def logout(user=Depends(current_user), cred: HTTPAuthorizationCredentials = Depends(bearer)):
    with db() as conn:
        conn.execute("DELETE FROM tokens WHERE token = ?", (cred.credentials,))
    return {"status": "logged_out"}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"username": user["username"]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
