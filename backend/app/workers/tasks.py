"""Celery 异步任务：文档解析 → 分块 → 向量化 → 索引。"""
import uuid
import time

from loguru import logger
from celery import Task
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import *
from app.workers.celery_app import celery_app
from app.utils.minio_client import minio_client
from app.utils.es_client import es_client
from app.utils.ai_client import embedding_client
from app.utils.doc_parser import parse_document
from app.services.chunker import chunk_text


class KBTask(Task):
    autoretry_for = (Exception,)
    max_retries = 3
    retry_backoff = True
    retry_backoff_max = 60


def _update_doc(db: Session, doc_id: str, **kwargs):
    doc = db.query(Document).filter_by(id=doc_id).first()
    if doc:
        for k, v in kwargs.items():
            setattr(doc, k, v)
        db.commit()
        return doc
    return None


def _update_task(db: Session, task_id: str, **kwargs):
    t = db.query(ProcessTask).filter_by(id=task_id).first()
    if t:
        for k, v in kwargs.items():
            setattr(t, k, v)
        db.commit()
        return t
    return None


@celery_app.task(base=KBTask, bind=True, name="kb.parse_document", queue="kb")
def parse_document_task(self, document_id: str, task_id: str):
    """阶段1：从 MinIO 读取文件 → 解析文本 → 存 PG。"""
    logger.info(f"[parse] start doc={document_id}")
    db = SessionLocal()
    try:
        # 更新状态
        _update_task(db, task_id, status="running", started_at=__import__("datetime").datetime.utcnow())
        _update_doc(db, document_id, status="parsing")

        doc = db.query(Document).filter_by(id=document_id).first()
        if not doc:
            _update_task(db, task_id, status="failed", error_message="文档不存在")
            return

        # 从 MinIO 读取
        data = minio_client.get_object(doc.minio_key)

        # 解析（MinerU / 本地轻量），返回 (markdown, meta)
        from app.parsing import parse_document as _parse
        text, meta = _parse(data, doc.filename, doc.file_type)

        # 存全文 + 元数据
        _update_doc(db, document_id, status="parsed", full_text=text, meta=meta)
        _update_task(db, task_id, status="success",
                     result=f"parsed {len(text)} chars",
                     finished_at=__import__("datetime").datetime.utcnow())

        # 链式触发下一阶段
        chunk_index_task.delay(document_id, task_id)
        logger.info(f"[parse] done doc={document_id} chars={len(text)}")

    except Exception as e:
        import traceback as _tb
        _err_msg = f"[parse] failed doc={document_id}: {e}\n{_tb.format_exc()}"
        logger.error(_err_msg)
        # 写错误到文件（worker stdout 可能未捕获）
        try:
            with open("/tmp/kb_worker_errors.log", "a") as _f:
                _f.write(_err_msg + "\n---\n")
        except Exception:
            pass
        _update_doc(db, document_id, status="failed", error_message=str(e)[:2000])
        _update_task(db, task_id, status="failed", error_message=str(e)[:2000],
                     finished_at=__import__("datetime").datetime.utcnow())
        raise
    finally:
        db.close()


@celery_app.task(base=KBTask, bind=True, name="kb.chunk_and_index", queue="kb")
def chunk_index_task(self, document_id: str, task_id: str):
    """阶段2：分块 → 批量 embedding → 写 ES。"""
    logger.info(f"[chunk_index] start doc={document_id}")
    db = SessionLocal()
    try:
        doc = db.query(Document).filter_by(id=document_id).first()
        if not doc:
            return
        if not doc.full_text:
            _update_task(db, task_id, status="failed", error_message="full_text 为空")
            return

        _update_doc(db, document_id, status="chunking")

        # 分块（参数来自全局配置 settings）
        chunks = chunk_text(doc.full_text, settings.rag_chunk_size, settings.rag_chunk_overlap)
        if not chunks:
            _update_doc(db, document_id, status="failed", error_message="分块结果为空")
            return

        # 批量 embedding（带重试）
        _update_doc(db, document_id, status="embedding")
        texts = [c["content"] for c in chunks]
        embeddings = []
        # 分批，每批 256，单批失败重试
        batch = 256
        for i in range(0, len(texts), batch):
            sub = texts[i:i + batch]
            for attempt in range(3):
                try:
                    vecs = embedding_client.embed(sub)
                    embeddings.extend(vecs)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    logger.warning(f"[chunk_index] embedding retry {attempt+1}: {e}")
                    time.sleep(2 ** attempt)

        # 写 PG chunk 记录
        for c in chunks:
            db.add(Chunk(
                id=uuid.UUID(c["chunk_id"]),
                document_id=uuid.UUID(document_id),
                kb_id=doc.kb_id,
                chunk_index=c["chunk_index"],
                content=c["content"],
                token_count=c["token_count"],
                metadata={},
            ))
        db.commit()

        # 写 ES
        from datetime import datetime
        es_chunks = [{
            "chunk_id": c["chunk_id"],
            "chunk_index": c["chunk_index"],
            "content": c["content"],
            "embedding": embeddings[i],
            "token_count": c["token_count"],
            "created_at": datetime.utcnow().isoformat(),
        } for i, c in enumerate(chunks)]

        es_client.ensure_index(embedding_dim=settings.embedding_dim)
        es_client.index_chunks(
            kb_id=str(doc.kb_id), document_id=document_id,
            file_name=doc.filename, file_type=doc.file_type,
            chunks=es_chunks,
        )

        _update_doc(db, document_id, status="indexed", chunk_count=len(chunks),
                    indexed_at=__import__("datetime").datetime.utcnow())
        _update_task(db, task_id, status="success",
                     result=f"indexed {len(chunks)} chunks",
                     finished_at=__import__("datetime").datetime.utcnow())
        logger.info(f"[chunk_index] done doc={document_id} chunks={len(chunks)}")

    except Exception as e:
        logger.error(f"[chunk_index] failed doc={document_id}: {e}")
        _update_doc(db, document_id, status="failed", error_message=str(e)[:2000])
        _update_task(db, task_id, status="failed", error_message=str(e)[:2000],
                     finished_at=__import__("datetime").datetime.utcnow())
        raise
    finally:
        db.close()


@celery_app.task(name="kb.cleanup_document", queue="kb")
def cleanup_document_task(document_id: str, minio_key: str, es_kb_id: str):
    """清理：删 ES chunks + MinIO 文件。"""
    try:
        es_client.delete_document(document_id)
        minio_client.remove_object(minio_key)
        logger.info(f"[cleanup] doc={document_id}")
    except Exception as e:
        logger.error(f"[cleanup] failed doc={document_id}: {e}")


@celery_app.task(name="kb.cleanup_kb", queue="kb")
def cleanup_kb_task(kb_id: str):
    """删除知识库时清理 ES 全部 chunks。"""
    try:
        es_client.delete_kb(kb_id)
        logger.info(f"[cleanup_kb] kb={kb_id}")
    except Exception as e:
        logger.error(f"[cleanup_kb] failed kb={kb_id}: {e}")
