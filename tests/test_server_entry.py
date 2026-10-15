"""第 1 条：main.py 必须真的把 uvicorn 拉起来（当前 start_server 被同名内层函数吞掉，空跑退出）。"""
import unittest
from unittest.mock import patch

import api.server as server


class StartServerTest(unittest.TestCase):
    def test_start_server_launches_uvicorn(self):
        with patch.object(server.uvicorn, "run") as run_mock:
            server.start_server()
        run_mock.assert_called_once()
        args, kwargs = run_mock.call_args
        self.assertIn("8000", str(args) + str(kwargs))


if __name__ == "__main__":
    unittest.main()
