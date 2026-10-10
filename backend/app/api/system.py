"""系统监控路由 /system"""
import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.responses import ok
from app.models import *
from app.api.deps import get_current_user, get_current_admin
from app.utils.es_client import es_client
from app.utils.minio_client import minio_client
from app.utils.ai_client import llm_client, EmbeddingHealth


router = APIRouter(tags=["系统监控"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    services = {}
    # PG
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        services["postgresql"] = "ok"
    except Exception:
        services["postgresql"] = "error"
    # ES
    try:
        h = es_client.es.cluster.health()
        services["elasticsearch"] = h.get("status", "ok")
    except Exception:
        services["elasticsearch"] = "unreachable"
    # MinIO
    try:
        minio_client.client
        services["minio"] = "ok"
    except Exception:
        services["minio"] = "unreachable"
    # Redis
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host=settings.redis_host, port=settings.redis_port,
                            password=settings.redis_password, socket_timeout=2)
        r.ping()
        services["redis"] = "ok"
    except Exception:
        services["redis"] = "unreachable"
    # LLM
    services["llm"] = "ok" if llm_client.health() else "unreachable"
    # Embedding
    services["embedding"] = "ok" if EmbeddingHealth.check() else "unreachable"
    # MinerU 解析服务
    from app.parsing.mineru_client import mineru_health
    mh = mineru_health()
    services["mineru"] = mh.get("status", "unreachable")

    overall = "ok" if all(s in ("ok", "green", "yellow") for s in services.values()) else "degraded"
    return ok({"status": overall, "services": services, "version": settings.app_version})


@router.get("/parse-engine")
def parse_engine(_admin: User = Depends(get_current_admin)):
    """MinerU 解析服务健康检查（admin）。"""
    import time
    from app.parsing.mineru_client import mineru_health
    t0 = time.time()
    h = mineru_health(timeout=5.0)
    latency_ms = int((time.time() - t0) * 1000)
    return ok({
        "status": h.get("status", "unreachable"),
        "url": settings.mineru_api_url,
        "backend": settings.mineru_backend,
        "latency_ms": latency_ms,
        **({"error": h["error"]} if "error" in h else {}),
    })


@router.get("/monitor")
def monitor(db: Session = Depends(get_db),
            _admin: User = Depends(get_current_admin)):
    # 文档统计
    total_docs = db.query(Document).filter(
        Document.is_deleted.is_(False)).count()
    stats = {}
    for status in ("indexed", "failed", "parsing", "parsed", "chunking", "embedding", "uploaded"):
        stats[status] = db.query(Document).filter(
            Document.status == status,
            Document.is_deleted.is_(False)).count()
    processing = stats.pop("parsing", 0) + stats.pop("chunking", 0) + stats.pop("embedding", 0) + stats.pop("parsed", 0) + stats.pop("uploaded", 0)
    chunk_count = db.query(Chunk).count()

    # ES
    es_info = {}
    try:
        es_info = es_client.es.indices.stats(index=settings.es_index)
        es_info = {
            "name": settings.es_index,
            "docs": es_info["total"]["docs"]["count"],
            "size_bytes": es_info["total"]["store"]["size_in_bytes"],
        }
    except Exception as e:
        es_info = {"error": str(e)}

    # MinIO
    minio_info = {}
    try:
        minio_info = {
            "bucket": "kb-docs",
            "objects": minio_client.count_objects(),
            "size_bytes": minio_client.bucket_size(),
        }
    except Exception as e:
        minio_info = {"error": str(e)}

    # Celery
    try:
        from app.workers.celery_app import celery_app
        insp = celery_app.control.inspect(timeout=2)
        active = insp.active() or {}
        reserved = insp.reserved() or {}
        celery_info = {
            "queue": "kb",
            "active": sum(len(v) for v in active.values()),
            "queued": sum(len(v) for v in reserved.values()),
        }
    except Exception:
        celery_info = {"queue": "kb", "active": 0, "queued": 0}

    return ok({
        "document_stats": {
            "total": total_docs,
            "indexed": stats.get("indexed", 0),
            "failed": stats.get("failed", 0),
            "processing": processing,
        },
        "chunk_count": chunk_count,
        "es_index": es_info,
        "minio": minio_info,
        "celery": celery_info,
        "kb_count": db.query(KnowledgeBase).filter(
            KnowledgeBase.is_deleted.is_(False)).count(),
        "user_count": db.query(User).count(),
    })
