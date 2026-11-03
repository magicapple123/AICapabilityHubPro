# G1：四服务同构镜像（多阶段：先装依赖再拷代码，利用层缓存）
FROM python:3.12-slim AS deps
WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN python -m pip install --disable-pip-version-check --no-cache-dir --retries 10 --timeout 60 \
    --index-url "${PIP_INDEX_URL}" -r requirements.lock.txt

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY app ./app
EXPOSE 8083
# 就绪探针走 /health/ready（B2）：它每次真查库，停库会立刻 503。
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3   CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8083/health/ready', timeout=2).status==200 else 1)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8083 --workers ${UVICORN_WORKERS:-2}"]
