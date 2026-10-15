"""第 5/6 条：接口必须校验 token；thread_id 与文件名不得穿越目录。"""
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

import api.server as server

USER = {"user_id": 1, "username": "tester"}


class UploadPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "output").mkdir()
        (root / "upload").mkdir()
        self._patches = [
            patch.object(server, "upload_dir", root / "upload"),
            patch.object(server, "output_dir", root / "output"),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(server.app)
        server.app.dependency_overrides[server.require_user] = lambda: USER
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(server.app.dependency_overrides.clear)

    def _upload(self, thread_id, filename, content=b"x"):
        return self.client.post(
            "/api/upload",
            data={"thread_id": thread_id},
            files={"files": (filename, content, "text/plain")},
        )

    def test_traversal_in_filename_contained(self):
        thread_id = f"utest_{uuid.uuid4().hex[:8]}"
        resp = self._upload(thread_id, "../../evil.txt")
        self.assertEqual(resp.status_code, 200, resp.text)
        upload_root = Path(server.upload_dir).resolve()
        escapes = [p for p in upload_root.parents if (p / "evil.txt").exists()]
        self.assertEqual(escapes, [], "文件名里的 ../ 逃出了 upload 目录")
        session_dir = upload_root / f"session_{thread_id}"
        names = [p.name for p in session_dir.iterdir()]
        self.assertTrue(names, "正常上传的文件必须仍然落盘")
        self.assertNotIn("..", names)

    def test_traversal_in_thread_id_rejected(self):
        for bad in ["../../escaped", "a/b", ".."]:
            resp = self._upload(bad, "a.txt")
            self.assertEqual(resp.status_code, 400, f"{bad} 应被拒绝，实得 {resp.status_code}")
        upload_root = Path(server.upload_dir).resolve()
        for parent in upload_root.parents:
            self.assertFalse((parent / "escaped").exists(), "thread_id 越界创建了目录")

    def test_task_rejects_traversal_thread_id(self):
        resp = self.client.post("/api/task", json={"query": "hi", "thread_id": "../escaped"})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_normal_upload_still_works(self):
        thread_id = f"utest_{uuid.uuid4().hex[:8]}"
        resp = self._upload(thread_id, "清单.txt", content="内容".encode())
        self.assertEqual(resp.status_code, 200, resp.text)
        saved = Path(server.upload_dir) / f"session_{thread_id}" / "清单.txt"
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_bytes(), "内容".encode())


class AuthRequiredTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.client.app.dependency_overrides.clear()

    def test_endpoints_reject_missing_token(self):
        cases = [
            ("get", "/api/files", {"path": "/app/output"}),
            ("post", "/api/upload", {}),
        ]
        for method, url, params in cases:
            resp = getattr(self.client, method)(url, params=params) if params else getattr(self.client, method)(url)
            self.assertEqual(resp.status_code, 401, f"{method.upper()} {url} 未鉴权仍可访问：{resp.status_code}")
        resp = self.client.post("/api/task", json={"query": "hi", "thread_id": "noauth"})
        self.assertEqual(resp.status_code, 401)
        resp = self.client.get("/api/download", params={"path": "/app/output/a.txt"})
        self.assertIn(resp.status_code, (401, 403))

    def test_health_is_open(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
