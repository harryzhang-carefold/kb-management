#!/usr/bin/env bash
# kb-management 后端启动脚本
# 显式设置 Redis 密码 + Celery broker URL（覆盖全局环境变量）
set -e
cd "$(dirname "$0")/../backend"
source .venv/bin/activate
# Clear any inherited CELERY env vars so config defaults take effect
unset CELERY_BROKER_URL CELERY_RESULT_BACKEND

# Redis 密码（与现有 redis 容器一致）

# Celery broker / result backend（含 URL 编码后的密码 %21 = !）

# 验证 redis 连通（参数取自 infra/.env → settings；不硬编码端口/密码）
python -c "from app.core.config import settings; import redis; print('[launcher] redis PING:', redis.Redis(host=settings.redis_host, port=settings.redis_port, password=settings.redis_password or None, socket_timeout=5).ping())"

echo "[launcher] starting uvicorn on :9012"
exec uvicorn app.main:app --host 0.0.0.0 --port 9012 --log-level info
