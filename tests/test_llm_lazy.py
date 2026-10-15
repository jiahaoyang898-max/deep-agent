"""第 2 条：模型必须惰性单例，模块 import 期不得构造（否则 key 缺失时后端整体起不来）。"""
import importlib
import sys
import unittest

import langchain.chat_models as cm


class LlmLazyTest(unittest.TestCase):
    def setUp(self):
        self._original = cm.init_chat_model
        sys.modules.pop("agent.llm", None)

    def tearDown(self):
        cm.init_chat_model = self._original
        sys.modules.pop("agent.llm", None)

    def _import_with(self, fake_init):
        cm.init_chat_model = fake_init
        return importlib.import_module("agent.llm")

    def test_import_does_not_construct_model(self):
        calls = []

        def boom(*args, **kwargs):
            calls.append(kwargs)
            raise AssertionError("init_chat_model 不应在 import 期被调用")

        module = self._import_with(boom)
        self.assertEqual(calls, [])
        self.assertTrue(hasattr(module, "get_model"), "agent.llm 应暴露 get_model()")

    def test_get_model_returns_cached_singleton(self):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return object()

        module = self._import_with(fake)
        first = module.get_model()
        second = module.get_model()
        self.assertIs(first, second, "多次 get_model() 必须返回同一实例")
        self.assertEqual(len(calls), 1, "模型只能构造一次")


if __name__ == "__main__":
    unittest.main()
