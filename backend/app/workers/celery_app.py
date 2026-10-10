"""Celery 应用配置。"""
from celery import Celery
from loguru import logger
import sys

# 配置 loguru 写入文件（worker 的 stdout 不被捕获）
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("/tmp/kb_worker.log", level="INFO", rotation="10 MB", retention="3 days", enqueue=True)

from app.core.config import settings

celery_app = Celery(
    "kb_management",
    broker=settings.celery_broker,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # embedding 失败重试
    task_default_retry_delay=5,
    task_time_limit=600,
    task_soft_time_limit=540,
    broker_connection_retry_on_startup=True,
    # 任务默认路由到 kb 队列（与 worker 的 -Q kb 一致）
    task_default_queue="kb",
    task_routes={"app.workers.tasks.*": {"queue": "kb"}},
)
