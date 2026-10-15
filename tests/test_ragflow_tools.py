"""第 3 条：知识库客户端惰性初始化 + 服务不可用时优雅降级（不抛异常炸链路）。"""
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class RagflowLazyTest(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.pop("tools.ragflow_tools", None)

    def tearDown(self):
        sys.modules.pop("tools.ragflow_tools", None)
        if self._saved is not None:
            sys.modules["tools.ragflow_tools"] = self._saved

    def test_import_survives_broken_credentials(self):
        with patch("ragflow_sdk.RAGFlow", side_effect=RuntimeError("api key 未配置")):
            module = importlib.import_module("tools.ragflow_tools")
        self.assertTrue(callable(module.get_client), "应提供惰性获取客户端的 get_client()")

    def test_tools_degrade_to_readable_message(self):
        module = importlib.import_module("tools.ragflow_tools")

        def broken_client():
            raise ConnectionError("知识库服务连不上: timed out")

        with patch.object(module, "get_client", broken_client):
            listed = module.get_assistant_list.invoke({})
            asked = module.create_ask_delete.invoke({"chat_name": "助手A", "question": "问题"})

        for result in (listed, asked):
            self.assertIn("知识库当前不可用", result)
            self.assertIn("timed out", result, "降级文案要带上真实原因")


if __name__ == "__main__":
    unittest.main()
