"""第 10/11 条：进度事件不得静默丢弃；WS 连接重复注册/误删要修。"""
import asyncio
import logging
import unittest

from api.context import _thread_id_ctx, set_thread_context
from api.monitor import ConnectionManager, monitor


class FakeSocket:
    def __init__(self, name):
        self.name = name
        self.sent = []
        self.closed = False

    async def accept(self):
        pass

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, *args, **kwargs):
        self.closed = True


class CapturingManager:
    """替身 ConnectionManager：记录 monitor 实际投递给哪个 thread_id。"""

    def __init__(self, loop):
        self.loop = loop
        self.delivered = []

    async def send_to_thread(self, payload, thread_id):
        self.delivered.append((thread_id, payload))


class ThreadIdRoutingTest(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self._saved_manager = monitor.websocket_manager

    def tearDown(self):
        monitor.websocket_manager = self._saved_manager
        self.loop.close()

    def test_event_from_worker_thread_reaches_manager(self):
        async def scenario():
            manager = CapturingManager(self.loop)
            monitor.websocket_manager = manager
            token = set_thread_context("thread-42")
            try:
                # 工具由 langgraph 丢进线程池执行，这里用 to_thread 复现同一形态
                await asyncio.to_thread(monitor.report_tool, "查询表", {"a": 1})
                await asyncio.sleep(0.05)
            finally:
                _thread_id_ctx.reset(token)
            return manager.delivered

        delivered = self.loop.run_until_complete(scenario())
        self.assertEqual(len(delivered), 1, "线程池里的进度事件不得丢失")
        self.assertEqual(delivered[0][0], "thread-42")

    def test_explicit_thread_id_used_when_context_missing(self):
        async def scenario():
            manager = CapturingManager(self.loop)
            monitor.websocket_manager = manager
            monitor.report_tool("查询表", {"a": 1}, thread_id="explicit-7")
            await asyncio.sleep(0.05)
            return manager.delivered

        delivered = self.loop.run_until_complete(scenario())
        self.assertEqual([t for t, _ in delivered], ["explicit-7"])

    def test_dropped_event_is_warned_not_silent(self):
        async def scenario():
            manager = CapturingManager(self.loop)
            monitor.websocket_manager = manager
            with self.assertLogs(level=logging.WARNING) as captured:
                monitor.report_tool("查询表", {"a": 1})
            await asyncio.sleep(0.05)
            return captured.output

        logs = self.loop.run_until_complete(scenario())
        self.assertTrue(any("thread_id" in line for line in logs), logs)


class ConnectionManagerTest(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.loop.close()

    def test_reconnect_closes_previous_socket(self):
        async def scenario():
            manager = ConnectionManager()
            old, new = FakeSocket("old"), FakeSocket("new")
            await manager.connect(old, "t1")
            await manager.connect(new, "t1")
            return manager, old

        manager, old = self.loop.run_until_complete(scenario())
        self.assertEqual(manager.active_connections["t1"].name, "new")
        self.assertTrue(old.closed, "同 thread_id 重连时旧 socket 必须关闭，否则泄漏")

    def test_stale_disconnect_does_not_remove_new_socket(self):
        async def scenario():
            manager = ConnectionManager()
            old, new = FakeSocket("old"), FakeSocket("new")
            await manager.connect(old, "t1")
            await manager.connect(new, "t1")
            manager.disconnect(old, "t1")  # 旧连接的断开事件迟到
            return manager

        manager = self.loop.run_until_complete(scenario())
        self.assertIn("t1", manager.active_connections, "旧连接的 disconnect 误删了新连接")
        self.assertEqual(manager.active_connections["t1"].name, "new")

    def test_matching_disconnect_removes_socket(self):
        async def scenario():
            manager = ConnectionManager()
            sock = FakeSocket("only")
            await manager.connect(sock, "t1")
            manager.disconnect(sock, "t1")
            return manager

        manager = self.loop.run_until_complete(scenario())
        self.assertNotIn("t1", manager.active_connections)


if __name__ == "__main__":
    unittest.main()
