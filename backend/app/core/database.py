"""SQLAlchemy 引擎与会话管理。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.debug,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """ORM 基类。"""


def get_db():
    """FastAPI 依赖：每请求一个 session，自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
