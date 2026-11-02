# G1：四服务同构镜像（多阶段：先装依赖再拷代码，利用层缓存）
FROM python:3.12-slim AS deps
WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
# 有 lock 就用 lock（可复现）；没有则退回范围约束，便于新服务渐进接入。
# lock 由 Windows venv 生成时会含平台专属包；Linux 装不上时回退到范围约束。
RUN pip install --no-cache-dir -r requirements.lock.txt \n    || pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY app ./app
EXPOSE 8081
# 就绪探针走 /health/ready（B2）：它每次真查库，停库会立刻 503。
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3   CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/health/ready', timeout=2).status==200 else 1)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8081 --workers ${UVICORN_WORKERS:-2}"]
