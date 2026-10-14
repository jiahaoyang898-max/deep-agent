# ============================================================
# 容器专用垫片（仅存在于 Linux 镜像，不影响 Windows 本机）
# 原因：utils/converter_utils.py 依赖 Windows 专属的 pywin32(Word COM) 转 PDF。
# 本文件在解释器启动时注册 win32com / pythoncom 的假模块，
# 将 Word 的 Open/SaveAs 映射为 WeasyPrint 的 HTML->PDF 真实转换。
# 业务代码零改动。
# ============================================================
import sys
import types
from pathlib import Path


class _FakeWordDocument:
    def __init__(self, html_path: str):
        self._html_path = html_path

    def SaveAs(self, target: str, FileFormat: int = 0, *args, **kwargs):
        # FileFormat 17 = wdFormatPDF（Word 语义），这里直接转 PDF
        if int(FileFormat) != 17:
            raise RuntimeError(f"仅支持导出 PDF（FileFormat=17），收到 {FileFormat}")
        from weasyprint import HTML  # 延迟导入

        Path(target).parent.mkdir(parents=True, exist_ok=True)
        HTML(filename=self._html_path).write_pdf(target)
        return True

    def Close(self, *args, **kwargs):
        pass


class _FakeWordDocuments:
    def Open(self, path: str, *args, **kwargs):
        return _FakeWordDocument(path)


class _FakeWordApp:
    def __init__(self):
        self.Visible = False
        self.DisplayAlerts = False
        self.Documents = _FakeWordDocuments()

    def Quit(self, *args, **kwargs):
        pass


def _dispatch(name: str):
    if name == "Word.Application":
        return _FakeWordApp()
    raise RuntimeError(f"容器环境不支持 COM 组件: {name}")


def _install_shim():
    # pythoncom：协程初始化在 Linux 上是空操作
    m_pythoncom = types.ModuleType("pythoncom")
    m_pythoncom.CoInitialize = lambda *a, **k: None
    m_pythoncom.CoUninitialize = lambda *a, **k: None

    # win32com / win32com.client
    m_win32com = types.ModuleType("win32com")
    m_client = types.ModuleType("win32com.client")
    m_client.Dispatch = _dispatch
    m_win32com.client = m_client

    sys.modules.setdefault("pythoncom", m_pythoncom)
    sys.modules.setdefault("win32com", m_win32com)
    sys.modules.setdefault("win32com.client", m_client)


_install_shim()
