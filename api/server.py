# [入口] FastAPI 服务端
import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import List

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from utils.logger_utils import logger

# Add project root to sys.path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

# Import agent runner and monitor
# 智能体与模型都是首次任务执行时才构建，import 期不再因为 key/网络问题卡死整个后端
from agent.main_agent import run_deep_agent
from api.monitor import manager

app = FastAPI(title="DeepAgents API")

# 挂载输出目录，以便前端访问生成的静态文件
# 假设输出目录位于项目根目录下的 output
output_dir = project_root / "output"
output_dir.mkdir(exist_ok=True)

# 定义上传目录 updated
upload_dir = project_root / "upload"
upload_dir.mkdir(exist_ok=True)

# 配置 CORS
# 生产形态下浏览器与后端在网关（docker/nginx.conf）下同源，且网关已 proxy_hide_header 剥掉上游 CORS 头，
# 通配 "*" + allow_credentials=True 既互斥又冗余。这里只接受显式白名单（本地/联调才需要），默认不挂中间件。
_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def startup_event():
    """
    服务启动时，获取当前运行的事件循环，并绑定到 WebSocket 管理器。
    确保后台线程能通过 run_coroutine_threadsafe 准确投递消息。
    """
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    logger.info(f"[Server] WebSocket Manager bound to loop: {id(loop)}")


# ====================== 鉴权（token 由 auth_service 签发，跨服务校验）======================
# 浏览器 WebSocket API 不能自定义请求头，所以 /ws 允许用 ?token= 传递；
# /api/download 由 <a href> 直接打开，同样支持 ?token=。
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")


def _auth_required() -> bool:
    """鉴权开关，默认开启；仅在明确设为 false/0/no/off 时关闭（本地排查用）。"""
    return os.getenv("AUTH_REQUIRED", "true").strip().lower() not in ("0", "false", "no", "off")


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.query_params.get("token") or None


async def _verify_token(token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{AUTH_SERVICE_URL}/api/auth/verify", json={"token": token})
    except Exception as e:
        logger.error(f"[Auth] 认证服务不可达: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail="认证服务不可用，请稍后重试")
    if resp.status_code == 200:
        return resp.json()
    raise HTTPException(status_code=401, detail="登录已过期或无效，请重新登录")


async def require_user(request: Request) -> dict:
    if not _auth_required():
        return {"user_id": 0, "username": "anonymous"}
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录：请求缺少访问令牌")
    return await _verify_token(token)


class TaskRequest(BaseModel):
    query: str
    thread_id: str = None


@app.get("/health")
async def health():
    """存活探针：供 docker compose healthcheck 使用，不需要鉴权。"""
    return {"status": "ok"}


def _session_dir_in(base_dir: Path, thread_id: str) -> Path:
    """把 thread_id 拼进会话目录：先拒绝路径分隔符，再 resolve 后校验没有越出 base_dir。"""
    tid = str(thread_id or "")
    if not tid or tid in (".", "..") or "/" in tid or "\\" in tid:
        raise HTTPException(status_code=400, detail="非法的会话 ID")
    base_abs = base_dir.resolve()
    target_dir = (base_abs / f"session_{tid}").resolve()
    if not target_dir.is_relative_to(base_abs):
        raise HTTPException(status_code=400, detail="非法的会话 ID")
    return target_dir


def _safe_filename(name: str) -> str:
    """剥离文件名里的目录成分（../、a/b\\c 等），只保留最终文件名。"""
    cleaned = Path(str(name or "").replace("\\", "/")).name
    if not cleaned or cleaned in (".", ".."):
        raise HTTPException(status_code=400, detail="非法的文件名")
    return cleaned


@app.post("/api/task")
async def run_task(request: TaskRequest, user: dict = Depends(require_user)):
    """
    智能体任务启动接口 (Run Agent Task)。

    目标：
    1. 接收用户的自然语言指令。
    2. 在后台异步启动 Agent 执行逻辑。
    3. 返回会话 ID，供前端通过 WebSocket 订阅实时进度。

    执行步骤：
    1. 获取或生成 thread_id（校验不越界）。
    2. 触发异步任务 (asyncio.create_task)。
    3. 立即返回响应，不阻塞 HTTP 线程。

    Args:
        request (TaskRequest): 包含用户 query 和可选 thread_id 的请求体。
    """
    # 1. [ID 初始化] thread_id 会参与 output/session_xxx 目录拼接，先校验再使用
    thread_id = request.thread_id or str(uuid.uuid4())
    _session_dir_in(output_dir, thread_id)

    # 2. [后台执行] 异步运行 Agent，不阻塞主线程
    # 注意：这里简单的使用 asyncio.create_task 触发，由 main_agent 内部负责实时推送
    asyncio.create_task(run_deep_agent(request.query, thread_id)) # 再将携程对象添加到当前事件循环中执行

    # 3. [立即响应]
    return {"status": "started", "thread_id": thread_id}


@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...), thread_id: str = Form(...),
                       user: dict = Depends(require_user)):
    """
    文件上传接口 (File Upload)。

    目标：
    1. 接收用户上传的一个或多个文件。
    2. 保存到 `upload/session_{thread_id}` 目录。
    3. 供 Agent 在后续任务中读取和分析。

    Args:
        files (List[UploadFile]): 文件对象列表。
        thread_id (str): 关联的任务会话 ID。
    """
    # 1. [目录准备] 确保上传目录存在，且未因 thread_id 越界
    target_dir = _session_dir_in(upload_dir, thread_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    # 2. [保存] 遍历并写入文件
    for file in files:
        filename = _safe_filename(file.filename)
        file_path = target_dir / filename
        # 使用二进制模式写入，支持各种文件格式 (图片、PDF、文本等)
        # shutil.copyfileobj 高效复制文件流，避免一次性加载大文件到内存
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved_files.append(filename)

    # 3. [响应] 返回成功保存的文件列表
    return {"status": "uploaded", "files": saved_files}

@app.get("/api/download")
async def download_file(path: str, user: dict = Depends(require_user)):
    """
    文件下载接口 (File Download)。

    目标：
    1. 根据绝对路径下载文件。
    2. 严格的安全检查，防止越权访问。

    Args:
        path (str): 文件的绝对路径 (通常从 list_files 接口获取)。
    """
    # 1. [安全检查] 路径解析与越权校验
    try:
        abs_path = Path(path).resolve()
        output_abs = output_dir.resolve()

        # 必须确保请求的文件在 output 目录下
        if not abs_path.is_relative_to(output_abs):
            raise HTTPException(status_code=403, detail="拒绝访问: 只能下载输出目录下的文件")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="无效的路径参数")

    # 2. [存在性检查]
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 3. [响应] 返回文件流 (浏览器自动触发下载)
    return FileResponse(abs_path, filename=abs_path.name)


@app.get("/api/files")
async def list_files(path: str, user: dict = Depends(require_user)):
    """
    文件列表查询接口 (File Explorer)。

    目标：
    1. 列出指定目录下的所有生成文件。
    2. 提供文件元数据（大小、时间、下载链接）。
    3. 严格的安全检查，防止路径遍历攻击。

    Args:
        path (str): 目标目录的绝对路径 (必须在 output 目录下)。
    """
    # 顶层兜底：任何异常都记完整堆栈到日志，对外只回固定文案，避免泄漏内部路径与实现细节
    try:
        logger.debug(f"[Files] 请求文件列表: {path}")

        # 1. [安全] 参数校验：必须是字符串
        if not path or not isinstance(path, str):
            return {"files": [], "error": "path 参数不能为空"}

        abs_path = Path(path).resolve()
        output_abs = output_dir.resolve()

        # 2. [安全] 检查路径是否越界
        if not abs_path.is_relative_to(output_abs):
            logger.warning(f"[Files] 拒绝访问: {abs_path} 不在 {output_abs} 目录下")
            return {"files": [], "error": "拒绝访问: 只能访问输出目录下的文件"}

        # 3. [检查] 目录是否存在
        if not abs_path.exists():
            logger.debug(f"[Files] 目录不存在: {abs_path}")
            return {"files": []}
        if not abs_path.is_dir():
            return {"files": [], "error": "路径不是目录"}

        files = []
        for file_path in abs_path.rglob("*"):
            try:
                if file_path.is_file():
                    stat = file_path.stat()
                    files.append({
                        "name": file_path.name,
                        "type": "file",
                        "path": str(file_path),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime
                    })
            except OSError as file_err:
                # 单个文件读不到，跳过，不影响整体
                logger.warning(f"[Files] 跳过文件 {file_path}: {file_err}")
                continue

        # 4. [排序] 按修改时间倒序
        files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        logger.debug(f"[Files] 找到 {len(files)} 个文件")
        return {"files": files}

    except Exception:
        logger.exception("[Files] list_files 处理异常")
        return {"files": [], "error": "服务器内部错误，请稍后重试"}

# 当浏览器请求 ws://localhost:8000/ws/thread_123 时：
# 1. 路由匹配 ：FastAPI 发现这个 URL 匹配了你写的 @app.websocket("/ws/{thread_id}") 。
# 2. 创建对象 ：FastAPI (基于 Starlette) 会立刻在 主事件循环 中实例化一个 WebSocket 对象。
#    - 这个对象封装了底层的 TCP 连接、HTTP 握手信息、以及后续的消息收发方法 ( send_text , receive_text 等)。
# 3. 注入参数 ：FastAPI 自动把这个刚创建好的 WebSocket 对象，作为参数传给你的 websocket_endpoint(websocket, ...) 函数。
@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    """
    WebSocket 实时通讯核心接口 (Real-time Communication)。

    目标：
    1. 建立长连接，实现服务端与前端的双向通信。
    2. 绑定 `thread_id`，实现会话级消息隔离。
    3. 维持心跳 (Keep-Alive)，防止连接超时。

    执行步骤：
    1. 鉴权：浏览器无法给 WebSocket 握手加请求头，故用 ?token= 传令牌。
    2. 握手：接受 WebSocket 连接请求。
    3. 注册：将连接实例绑定到 `monitor.manager`，关联 `thread_id`。
    4. 循环：进入消息监听循环，处理前端发送的心跳或指令。
    5. 异常：捕获断开连接异常，清理资源。

    Args:
        websocket (WebSocket): WebSocket 连接实例。
        thread_id (str): 当前会话的唯一标识。
    """
    # 1. [鉴权] 未通过校验直接拒绝握手，不能匿名订阅他人会话
    if _auth_required():
        token = _extract_token(websocket)
        if not token:
            logger.warning(f"[WebSocket] 拒绝未鉴权连接: thread_id={thread_id}")
            await websocket.close(code=4401)
            return
        try:
            await _verify_token(token)
        except HTTPException as e:
            logger.warning(f"[WebSocket] 鉴权失败 thread_id={thread_id}: {e.detail}")
            await websocket.close(code=4401)
            return

    # 2. [注册] 建立连接并绑定到管理器
    await manager.connect(websocket, thread_id)

    try:
        # 3. [循环] 保持连接活跃
        while True:
            # 4. [监听] 接收前端消息 (通常是 ping 心跳)
            data = await websocket.receive_text()

            # 5. [响应] 回复 pong 消息
            await websocket.send_json({
                "type": "pong",
                "message": f"服务端已收到: {data}"
            })

    except WebSocketDisconnect:
        # 6. [清理] 客户端主动断开
        manager.disconnect(websocket, thread_id)
        logger.debug(f"[WebSocket] 客户端已断开: {thread_id}")

    except Exception as e:
        # 7. [异常] 发生错误时断开
        logger.warning(f"[WebSocket] 连接异常: {e}")
        manager.disconnect(websocket, thread_id)


def start_server():
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
