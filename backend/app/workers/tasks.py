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

        # 存全文 + 元数据（v2：保留 index_type，解析 meta 不覆盖）
        new_meta = dict(meta or {})
        old_meta = dict(doc.meta or {})
        new_meta["index_type"] = old_meta.get("index_type", "embedding")
        _update_doc(db, document_id, status="parsed", full_text=text, meta=new_meta)
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
    """阶段2：分块 → 批量 embedding → 写 ES。

    v2：按文档 index_type 分流——
    - "pageindex"：跳过分块/向量（一个文档只建一种索引），直接链式触发 PageIndex 建树
    - 其他（"embedding"/旧文档）：原有 chunk+ES 路径，行为不变
    """
    logger.info(f"[chunk_index] start doc={document_id}")
    db = SessionLocal()
    try:
        doc = db.query(Document).filter_by(id=document_id).first()
        if not doc:
            return
        if not doc.full_text:
            _update_task(db, task_id, status="failed", error_message="full_text 为空")
            return

        # v2：按文档 index_type 分流（默认 embedding 保持现有行为）
        if (doc.meta or {}).get("index_type") == "pageindex":
            logger.info(f"[chunk_index] doc={document_id} index_type=pageindex → 跳过 chunk/向量索引，直接建树")
            _update_task(db, task_id, status="success",
                         result="skipped (index_type=pageindex)",
                         finished_at=__import__("datetime").datetime.utcnow())
            _queue_pageindex_build(db, doc, document_id)
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


def _queue_pageindex_build(db: Session, doc: Document, document_id: str):
    """链式触发 PageIndex 建树（按文档 index_type 决策，v2）。

    触发点：chunk_index_task 对 pageindex 文档的分流处 / reparse 后。
    触发失败只记日志，不影响主流程。
    """
    try:
        # 显式生成 id：避免依赖 commit/refresh 回填（回填时序受 expire_on_commit
        # 影响，曾导致 delay(str(task.id)) 传 "None"）
        pi_task = ProcessTask(id=uuid.uuid4(), document_id=document_id,
                              task_type="pageindex", status="pending")
        db.add(pi_task)
        db.commit()
        build_pageindex_task.delay(document_id, str(pi_task.id))
        logger.info(f"[chunk_index] pageindex build queued doc={document_id} task={pi_task.id}")
    except Exception as e:
        logger.error(f"[chunk_index] pageindex trigger failed doc={document_id}: {e}")


@celery_app.task(base=KBTask, bind=True, name="kb.build_pageindex", queue="kb",
                 time_limit=900, soft_time_limit=840)
def build_pageindex_task(self, document_id: str, task_id: str):
    """阶段3：PageIndex 树索引构建（LLM 密集，30-120s）。

    触发条件（v2）：文档 meta.index_type == "pageindex"（上传时按文档二选一），
    或 rebuild API / reparse 链式触发（重建按该文档的 index_type 执行）。

    失败**不得**把 document.status 置 failed，
    只写 meta.pageindex_status='failed' + ProcessTask.error_message。
    """
    from datetime import datetime
    from app.services.pageindex_engine import build_tree_index
    logger.info(f"[pageindex_build] start doc={document_id}")
    db = SessionLocal()
    try:
        _update_task(db, task_id, status="running", started_at=datetime.utcnow())
        doc = db.query(Document).filter_by(id=document_id).first()
        if not doc:
            _update_task(db, task_id, status="failed", error_message="文档不存在")
            return
        if (doc.meta or {}).get("index_type") != "pageindex":
            _update_task(db, task_id, status="failed",
                         error_message="该文档 index_type 不是 pageindex，无需建树")
            return
        if not doc.full_text:
            _update_task(db, task_id, status="failed", error_message="full_text 为空")
            meta = dict(doc.meta or {})
            meta["pageindex_status"] = "failed"
            doc.meta = meta
            db.commit()
            return

        # 标记 building + 状态置为索引中（pageindex 文档的唯一索引阶段）
        doc.status = "chunking"
        meta = dict(doc.meta or {})
        meta["pageindex_status"] = "building"
        doc.meta = meta
        db.commit()

        tree_meta = build_tree_index(doc, db)

        # 刷新 doc 读取最新 meta（build_tree_index 已 commit）
        db.expire_all()
        doc = db.query(Document).filter_by(id=document_id).first()
        status = (doc.meta or {}).get("pageindex_status", tree_meta.get("status", "ok"))
        # 树建好（ok/degraded）→ 文档就绪，状态置 indexed（pageindex 文档的唯一索引）
        if status in ("ok", "degraded"):
            doc.status = "indexed"
            doc.indexed_at = datetime.utcnow()
            db.commit()
        _update_task(db, task_id, status="success",
                     result=f"pageindex tree: status={status} "
                            f"nodes={tree_meta.get('node_count')} "
                            f"build_ms={tree_meta.get('build_ms')}",
                     finished_at=datetime.utcnow())
        logger.info(f"[pageindex_build] done doc={document_id} status={status}")

    except Exception as e:
        import traceback as _tb
        err = f"[pageindex_build] failed doc={document_id}: {e}\n{_tb.format_exc()}"
        logger.error(err)
        try:
            with open("/tmp/kb_worker_errors.log", "a") as _f:
                _f.write(err + "\n---\n")
        except Exception:
            pass
        # pageindex 文档建树失败 = 无可用索引 → 状态置 failed（v2 无 chunk 兜底）
        doc = db.query(Document).filter_by(id=document_id).first()
        if doc:
            meta = dict(doc.meta or {})
            meta["pageindex_status"] = "failed"
            doc.meta = meta
            doc.status = "failed"
            doc.error_message = str(e)[:2000]
            db.commit()
        _update_task(db, task_id, status="failed", error_message=str(e)[:2000],
                     finished_at=datetime.utcnow())
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
