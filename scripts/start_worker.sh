#!/usr/bin/env bash
# kb-management Celery worker 启动脚本
set -e
cd "$(dirname "$0")/../backend"
source .venv/bin/activate
# Clear any inherited CELERY env vars so config defaults take effect
unset CELERY_BROKER_URL CELERY_RESULT_BACKEND


echo "[worker] starting celery worker"
exec celery -A app.workers.celery_app.celery_app worker --loglevel=info --concurrency=2 -Q kb
