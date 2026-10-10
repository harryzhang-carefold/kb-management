"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# 配置 loguru 同时写入文件（后台进程不捕获 stderr）
import sys
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("/tmp/kb_app.log", level="INFO", rotation="10 MB", retention="3 days", enqueue=True)

from app.core.config import settings
from app.core.database import engine, Base
from app.core.responses import exception_handler
from app.api import auth, users, knowledge_bases, documents, search, chat, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：确保 ES 索引 + MinIO bucket 存在
    try:
        from app.utils.es_client import es_client
        es_client.ensure_index(embedding_dim=3584)
        logger.info("ES index ready")
    except Exception as e:
        logger.warning(f"ES init skipped: {e}")
    try:
        from app.utils.minio_client import minio_client
        minio_client.client  # 触发 bucket 创建
        logger.info("MinIO bucket ready")
    except Exception as e:
        logger.warning(f"MinIO init skipped: {e}")
    logger.info(f"{settings.app_name} v{settings.app_version} started")
    yield
    logger.info("shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="知识库管理系统 API",
        version=settings.app_version,
        lifespan=lifespan,
    )

    # 全局异常处理
    app.add_exception_handler(Exception, exception_handler)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(knowledge_bases.router, prefix=prefix)
    app.include_router(documents.router, prefix=prefix)
    app.include_router(search.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(system.router, prefix=prefix)

    @app.get("/", tags=["根"])
    def root():
        return {"name": settings.app_name, "version": settings.app_version,
                "docs": f"{prefix}/docs"}

    return app


app = create_app()
