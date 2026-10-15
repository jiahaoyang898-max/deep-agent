"""第 2/4 条：主智能体惰性构建（全会话共用一个实例）+ 失败原因必须回传前端。"""
import asyncio
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import openai

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _auth_error() -> openai.AuthenticationError:
    import httpx2 as httpx

    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://example.invalid/chat/completions"),
        json={"error": {"message": "Invalid API-key provided.", "type": "invalid_request_error"}},
    )
    return openai.AuthenticationError("Error code: 401 - Invalid API-key provided.", response=response, body=None)


class FakeAgent:
    """替身智能体：astream 返回一个立刻抛出指定异常的异步生成器。"""

    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    def astream(self, _payload):
        self.calls += 1

        async def _gen():
            raise self.error
            yield {}

        return _gen()


class MainAgentLazyTest(unittest.TestCase):
    def setUp(self):
        self._originals = {n: sys.modules.get(n) for n in ("agent.main_agent",)}
        sys.modules.pop("agent.main_agent", None)
        self.thread_id = f"utest_{uuid.uuid4().hex[:8]}"
        self.session_dir = PROJECT_ROOT / "output" / f"session_{self.thread_id}"

    def tearDown(self):
        sys.modules.pop("agent.main_agent", None)
        if self.session_dir.exists():
            shutil.rmtree(self.session_dir, ignore_errors=True)

    def _import_with(self, factory):
        with patch("deepagents.create_deep_agent", factory):
            import agent.main_agent as module

        return module

    def test_import_does_not_build_agent(self):
        calls = []
        module = self._import_with(lambda **kw: calls.append(kw) or FakeAgent(RuntimeError("unused")))
        self.assertEqual(calls, [], "create_deep_agent 不应在 import 期执行")
        self.assertTrue(hasattr(module, "get_main_agent"), "应暴露 get_main_agent()")

    def test_agent_built_once_and_reused(self):
        built = []
        module = self._import_with(lambda **kw: built.append(kw) or FakeAgent(_auth_error()))
        with patch.object(module.monitor, "_emit"):
            for _ in range(3):
                asyncio.run(module.run_deep_agent("测试问题", self.thread_id))
        self.assertEqual(len(built), 1, "智能体必须只构建一次并复用（否则丢会话状态且更慢）")
        self.assertEqual(module.get_main_agent().calls, 3)

    def test_auth_failure_reports_actionable_reason(self):
        emitted = []
        module = self._import_with(lambda **kw: FakeAgent(_auth_error()))
        with patch.object(module.monitor, "_emit", side_effect=lambda *a, **k: emitted.append(a)):
            asyncio.run(module.run_deep_agent("测试问题", self.thread_id))

        errors = [args[1] for args in emitted if args and args[0] == "error"]
        self.assertEqual(len(errors), 1, f"失败时必须发出一条 error 事件，实得 {emitted}")
        message = errors[0]
        self.assertNotIn("智能体执行最终失败了", message, "禁止再回传无信息量的兜底文案")
        self.assertIn("API Key", message)
        self.assertIn("DASHSCOPE_API_KEY", message)

    def test_other_failures_are_distinguishable(self):
        module = self._import_with(lambda **kw: FakeAgent(RuntimeError("unused")))
        cases = {
            _auth_error(): ("API Key", "DASHSCOPE_API_KEY"),
            TimeoutError("connect timeout after 30 seconds"): ("超时",),
            OSError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"): ("SSL",),
            RuntimeError("column 'x' not found"): ("RuntimeError",),
        }
        for error, expected in cases.items():
            message = module.describe_agent_failure(error)
            for token in expected:
                self.assertIn(token, message, f"{type(error).__name__} 的提示应包含 {token}，实得：{message}")
        distinct = {module.describe_agent_failure(e) for e in cases}
        self.assertEqual(len(distinct), len(cases), "不同根因必须给出可区分的原因文案")


if __name__ == "__main__":
    unittest.main()
