# 03_task_push.py
import asyncio
import uuid
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # 允许所有来源（开发够用，生产按需收紧）
    allow_credentials=True,
    allow_methods=["*"],    # 关键：允许 POST / GET / OPTIONS 等所有方法
    allow_headers=["*"],    # 关键：允许带 Content-Type 等请求头
)

# ---- ConnectionManager（与 Demo 2 相同，略去注释） ----
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, thread_id: str):
        await websocket.accept()
        self.active_connections[thread_id] = websocket

    def disconnect(self, thread_id: str):
        self.active_connections.pop(thread_id, None)

    async def send_to_thread(self, message: dict, thread_id: str):
        if thread_id in self.active_connections:
            await self.active_connections[thread_id].send_json(message)

manager = ConnectionManager()


# ---- 业务：模拟一个耗时任务（对应你的 Agent 执行） ----
async def run_long_task(query: str, thread_id: str):
    """模拟 Agent 的思考过程：多次 sleep + 推送进度"""
    steps = [
        ("思考", "正在分析任务需求..."),
        ("工具", "正在调用网络搜索助手..."),
        ("工具", "正在查询数据库..."),
        ("生成", "正在生成报告..."),
    ]
    for step_type, msg in steps:
        await asyncio.sleep(1)  # 模拟耗时
        # 关键：向这个 thread_id 定向推送进度
        await manager.send_to_thread(
            {"type": "monitor_event", "step": step_type, "message": msg},
            thread_id,
        )
    await manager.send_to_thread(
        {"type": "task_result", "message": f"任务完成！你的问题是: {query}"},
        thread_id,
    )


# ---- HTTP 接口：提交任务，立即返回 ----
class TaskRequest(BaseModel):
    query: str
    thread_id: str | None = None


@app.post("/api/task")
async def run_task(request: TaskRequest):
    thread_id = request.thread_id or str(uuid.uuid4())

    # 关键：create_task 把任务放到后台执行，不阻塞当前请求
    # （对应你项目里 asyncio.create_task(run_deep_agent(...))）
    asyncio.create_task(run_long_task(request.query, thread_id))

    # 立即返回，让前端拿到 thread_id 后去连 WebSocket
    return {"status": "started", "thread_id": thread_id}


# ---- WebSocket：订阅某个 thread_id 的进度 ----
@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    await manager.connect(websocket, thread_id)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "pong", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(thread_id)