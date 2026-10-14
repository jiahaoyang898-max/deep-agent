# ---- 认证微服务 ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install --no-cache-dir --timeout 120 --retries 6 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7"

COPY auth_service/main.py ./main.py

EXPOSE 8001

VOLUME ["/data"]

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
