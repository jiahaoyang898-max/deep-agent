"""第 18 条：path_utils 不得因路径含 upload/ 就跳出会话目录。"""
import os
import tempfile
import unittest
from pathlib import Path

from utils.path_utils import resolve_path


class UploadPathIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session = Path(self.tmp.name).resolve() / "session_123"
        self.session.mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def _assert_inside_session(self, filename):
        resolved = Path(resolve_path(filename, str(self.session))).resolve()
        self.assertTrue(
            resolved.is_relative_to(self.session) or resolved == self.session,
            f"{filename} 解析出了会话目录：{resolved}",
        )
        return resolved

    def test_upload_prefix_stays_in_session(self):
        resolved = self._assert_inside_session("upload/报告.pdf")
        self.assertEqual(resolved.name, "报告.pdf")

    def test_upload_traversal_blocked(self):
        self._assert_inside_session("upload/../../outside.txt")
        self._assert_inside_session("abc/upload/../../secrets.env")

    def test_plain_traversal_blocked(self):
        self._assert_inside_session("../../outside.txt")
        self._assert_inside_session("sub/../../secrets.env")

    def test_normal_relative_path_still_resolves(self):
        resolved = self._assert_inside_session("sub/清单.md")
        self.assertEqual(resolved, self.session / "sub" / "清单.md")


if __name__ == "__main__":
    unittest.main()
