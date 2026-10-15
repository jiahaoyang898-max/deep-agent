# [核心] WebSocket 监控
import datetime
import asyncio
from utils.logger_utils import logger
from typing import Any, Dict, Optional
from fastapi import WebSocket
from api.context import get_thread_context
import builtins # 用于脚本模式下的流式输出

class ToolMonitor:
    """
    工具监控类，用于在工具执行过程中上报进度和状态。
    设计为单例模式，可在任何工具中直接导入使用。
    兼容 FastAPI WebSocket 和 脚本运行时的 stream_writer。

    使用示例:
    from api.monitor import monitor

    def my_tool(arg1):
        monitor.report_start("my_tool", {"arg1": arg1})
        ...
        monitor.report_running("my_tool", "正在处理数据...", progress=0.5)
        ...
        monitor.report_end("my_tool", result)
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolMonitor, cls).__new__(cls)
            cls._instance.websocket_manager = None  # 预留给 FastAPI WebSocketManager
        return cls._instance

    def set_websocket_manager(self, manager):
        """设置 FastAPI 的 WebSocket 管理器"""
        self.websocket_manager = manager

    def _emit(self, event_type: str, message: str, data: Optional[Dict[str, Any]] = None,
              thread_id: Optional[str] = None):
        """内部发送方法。thread_id 显式传入时优先于 contextvar（线程池/跨任务场景不再静默丢事件）。"""
        payload = {
            "type": "monitor_event",
            "event": event_type,
            "message": message,
            "data": data or {},
            "timestamp": datetime.datetime.now().isoformat()
        }

        # 1. 优先尝试通过 FastAPI WebSocket 发送 (定向推送)
        if self.websocket_manager:
            try:
                # 获取当前线程 ID
                target_thread_id = thread_id or get_thread_context()

                # 确保 loop 已加载
                manager_loop = self.websocket_manager.loop

                if manager_loop:
                    if target_thread_id:
                        # 检查当前是否在同一个事件循环中
                        try:
                            current_loop = asyncio.get_running_loop()
                        except RuntimeError:
                            current_loop = None

                        if current_loop and current_loop == manager_loop:
                            # 如果在同一个循环中（例如在 create_task 中运行），直接创建任务
                            current_loop.create_task(
                                self.websocket_manager.send_to_thread(payload, target_thread_id)
                            )
                        else:
                            #  FastAPI 的 WebSocket 依赖异步事件循环，且协程必须在创建它的循环中运行：
                            #  如果当前线程和 WebSocket 管理器在同一个循环（比如在 FastAPI 的接口 / 任务中运行）：直接 create_task 效率最高；
                            #  如果在不同循环 / 不同线程（比如同步线程调用）：必须用 asyncio.run_coroutine_threadsafe（线程安全的方式），否则会报错 “协程在错误的循环中运行”。
                            # 如果在不同线程，使用 threadsafe 方法
                            asyncio.run_coroutine_threadsafe(
                                self.websocket_manager.send_to_thread(payload, target_thread_id),
                                manager_loop
                            )
                    else:
                        # 静默丢弃会让前端右侧工具日志莫名缺行，必须留痕
                        logger.warning(f"[Monitor] 事件缺少 thread_id，无法定向推送，已丢弃: {event_type} | {message}")
            except Exception as e:
                logger.error(f"[Monitor] WebSocket send failed: {e}")

        # 2. 尝试通过全局 runtime 输出 (DeepAgents 脚本模式)
        # 这使得 simple_agents.py 中的 MockRuntime 能接收到数据
        if builtins and hasattr(builtins, 'runtime') and hasattr(builtins.runtime, 'stream_writer'):
            try:
                builtins.runtime.stream_writer(payload)
            except Exception:
                pass

        # 3. 控制台保底输出 (方便调试)
        logger.debug(f"[Monitor:{event_type}] {message}")

    def report_tool(self, tool_name: str, args: Dict[str, Any] = None,
                    thread_id: Optional[str] = None):
        """报告工具开始执行"""
        self._emit("tool_start", f"开始执行工具: {tool_name}", {"tool_name": tool_name, "args": args},
                   thread_id=thread_id)

    def report_assistant(self, assistant_name: str, args: Dict[str, Any] = None,
                         thread_id: Optional[str] = None):
        """报告正在调用的子智能体进度"""
        self._emit("assistant_call", f"正在调用助手: {assistant_name}",
                   {"assistant_name": assistant_name, "args": args}, thread_id=thread_id)

    def report_task_result(self, result: str, thread_id: Optional[str] = None):
        """报告任务最终结果"""
        self._emit("task_result", "任务执行完成", {"result": result}, thread_id=thread_id)

    def report_session_dir(self, path: str, thread_id: Optional[str] = None):
        """报告任务工作目录"""
        self._emit("session_created", f"工作目录已创建: {path}", {"path": path}, thread_id=thread_id)

    def report_error(self, message: str, thread_id: Optional[str] = None):
        """报告失败原因（message 会直接显示在前端，必须是可读、可行动的原因）"""
        self._emit("error", message, thread_id=thread_id)


# 全局单例实例
monitor = ToolMonitor()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        # 延迟绑定 loop，防止初始化时 loop 不一致
        self.loop = None

    def set_loop(self, loop):
        """显式设置事件循环"""
        self.loop = loop
        monitor.set_websocket_manager(self)
        logger.debug(f"[Monitor] ConnectionManager manually bound to loop: {id(self.loop)}")

    async def connect(self, websocket: WebSocket, thread_id: str):
        await websocket.accept()
        previous = self.active_connections.get(thread_id)
        if previous is not None and previous is not websocket:
            # 前端刷新/重连会用同一个 thread_id 再建一条连接；不关旧的就永久泄漏一条 socket
            self.active_connections.pop(thread_id, None)
            try:
                await previous.close()
            except Exception as e:
                logger.debug(f"[Monitor] 关闭旧连接失败 {thread_id}: {e}")
        self.active_connections[thread_id] = websocket
        logger.debug(f"Client connected: {thread_id}")

    def disconnect(self, websocket: WebSocket, thread_id: str):
        current = self.active_connections.get(thread_id)
        if current is None:
            logger.debug(f"Client disconnected (already gone): {thread_id}")
            return
        if current is not websocket:
            # 旧连接迟到的断开事件不能误删当前连接
            logger.debug(f"[Monitor] 忽略旧连接的断开事件: {thread_id}")
            return
        del self.active_connections[thread_id]
        logger.debug(f"Client disconnected: {thread_id}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def send_to_thread(self, message: dict, thread_id: str):
        websocket = self.active_connections.get(thread_id)
        if websocket is None:
            # 前端还没连上（或已断开）时事件确实到不了页面，留痕便于排查"进度不显示"
            logger.debug(f"[Monitor] 无活动连接，事件未推送: {thread_id} | {message.get('event')}")
            return
        await websocket.send_json(message)

manager = ConnectionManager()
