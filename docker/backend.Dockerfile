# ---- 后端（FastAPI + 智能体）----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖，充分利用层缓存（使用国内镜像源，避免 PyPI 超时）
COPY docker/requirements-docker.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 6 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        -r /tmp/requirements.txt && \
    pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple "weasyprint>=61"

# WeasyPrint 渲染 PDF 需要的 pango / 中文字体
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

# 注入 win32com 垫片：让原代码的 Word COM 转 PDF 在 Linux 上走 WeasyPrint（业务代码零改动）
COPY docker/shim/sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py

# 拷贝业务代码（.env 由 compose 挂载，不打入镜像）
COPY agent/ ./agent/
COPY api/ ./api/
COPY prompt/ ./prompt/
COPY tools/ ./tools/
COPY utils/ ./utils/
COPY main.py ./

EXPOSE 8000

# 生产模式直接跑 uvicorn（不用 reload），原代码零改动
CMD ["python", "-m", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
