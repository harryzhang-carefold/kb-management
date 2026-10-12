"""文档路由 /knowledge-bases/{kb_id}/documents"""
import uuid
import io

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.config import settings
from app.core.database import get_db
from app.core.responses import ok, not_found, param_error
from app.schemas import schemas
from app.models import *
from app.api.deps import get_current_user, get_current_user_or_view_token, require_kb_access, ViewTokenContext
from app.workers.tasks import parse_document_task, cleanup_document_task
from app.utils.doc_parser import detect_file_type
from app.utils.minio_client import minio_client
from app.utils.es_client import es_client

router = APIRouter(tags=["文档管理"])

MAX_SIZE = settings.rag_max_file_size_mb * 1024 * 1024

# file_type → MIME 映射（download 端点 inline 渲染用，V2 §1 错误3）
_DOWNLOAD_MIME = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "bmp": "image/bmp",
    "webp": "image/webp",
    "tiff": "image/tiff",
    "svg": "image/svg+xml",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
}


def _download_mime(file_type: str) -> str:
    return _DOWNLOAD_MIME.get((file_type or "").lower(), "application/octet-stream")


@router.get("/knowledge-bases/{kb_id}/documents")
def list_docs(kb_id: UUID,
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              status: str | None = None, keyword: str | None = None,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    q = db.query(Document).filter(
        Document.kb_id == kb_id, Document.is_deleted.is_(False))
    if status:
        q = q.filter(Document.status == status)
    if keyword:
        q = q.filter(Document.filename.ilike(f"%{keyword}%"))
    total = q.count()
    items = q.order_by(Document.uploaded_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return ok({
        "items": [schemas.DocOut.model_validate(d) for d in items],
        "total": total, "page": page, "page_size": page_size,
    })


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_doc(kb_id: UUID,
                     file: UploadFile = File(...),
                     index_type: str = Form("pageindex", pattern="^(embedding|pageindex)$"),
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """上传文档。

    index_type（v2，按文档二选一，互斥）：
    - "pageindex"（默认，新文档走树索引）：解析 → 分块+向量索引（保留原文/锚点）→ 异步构建 PageIndex 树索引
    - "embedding"：解析 → 分块 → 向量索引（ES）
    文档自身记录 index_type 到 meta，重建索引按此执行。
    注：历史无 index_type 的文档仍按 embedding 兜底处理（见 workers/tasks.py 分流）。
    """
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")

    # 文件类型
    ftype = detect_file_type(file.filename or "")
    if not ftype or ftype == "xls":
        if ftype == "xls":
            raise param_error("不支持 .xls 格式，请另存为 .xlsx 后重新上传")
        raise param_error(f"不支持的文件类型: {file.filename}")

    # 读取内容
    data = await file.read()
    # 按类型大小上限校验
    max_mb = settings.max_file_size_mb(ftype)
    if len(data) > max_mb * 1024 * 1024:
        raise param_error(f"文件过大（{ftype} 上限 {max_mb}MB）")

    # 存 MinIO
    doc_id = str(uuid.uuid4())
    minio_key = f"kb/{kb_id}/doc/{doc_id}.{ftype}"
    minio_client.put_object(minio_key, data, content_type=file.content_type or "application/octet-stream")

    # 建 document（v2：记录该文档的索引方式 index_type，二选一互斥）
    doc = Document(
        kb_id=kb_id, uploaded_by=user.id,
        filename=file.filename or "unnamed", file_type=ftype,
        file_size=len(data), minio_key=minio_key, status="uploaded",
        meta={"index_type": index_type},
    )
    db.add(doc)
    db.flush()  # 生成 doc.id
    # 建 task 记录
    task = ProcessTask(document_id=doc.id, task_type="parse", status="pending")
    db.add(task)
    db.commit()
    db.refresh(doc)
    db.refresh(task)

    # 入队解析
    from loguru import logger as _log
    try:
        async_res = parse_document_task.delay(str(doc.id), str(task.id))
        _log.info(f"[upload] task published: doc={doc.id} task={task.id} celery_id={async_res.id}")
    except Exception as e:
        _log.error(f"[upload] task publish FAILED: doc={doc_id} err={e}")
        raise

    return ok(schemas.DocUploadOut(document_id=doc.id, status=doc.status, task_id=task.id))


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}")
def get_doc(kb_id: UUID, doc_id: UUID,
            db: Session = Depends(get_db),
            user: User | ViewTokenContext = Depends(get_current_user_or_view_token)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id, is_deleted=False).first()
    if not doc:
        raise not_found("文档不存在")
    task = db.query(ProcessTask).filter(
        ProcessTask.document_id == doc_id
    ).order_by(ProcessTask.created_at.desc()).first()
    return ok(schemas.DocDetailOut(
        document=schemas.DocOut.model_validate(doc),
        task=schemas.ProcessTaskOut.model_validate(task) if task else None,
    ))


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/download")
def download_doc(kb_id: UUID, doc_id: UUID,
                 db: Session = Depends(get_db),
                 user: User | ViewTokenContext = Depends(get_current_user_or_view_token)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id, is_deleted=False).first()
    if not doc:
        raise not_found("文档不存在")
    data = minio_client.get_object(doc.minio_key)
    # inline + 按 file_type 映射 MIME（供 iframe 渲染，V2 §1 错误3）
    return StreamingResponse(
        io.BytesIO(data),
        media_type=_download_mime(doc.file_type),
        headers={"Content-Disposition": f"inline; filename={doc.filename}"},
    )


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/content")
def get_doc_content(kb_id: UUID, doc_id: UUID,
                    db: Session = Depends(get_db),
                    user: User | ViewTokenContext = Depends(get_current_user_or_view_token)):
    """查看文档原文内容（解析后的纯文本）"""
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id, is_deleted=False).first()
    if not doc:
        raise not_found("文档不存在")
    if not doc.full_text:
        raise param_error("文档尚未解析完成，暂无原文内容")
    return ok({
        "filename": doc.filename,
        "file_type": doc.file_type,
        "content": doc.full_text,
        "chunk_count": doc.chunk_count,
        "meta": doc.meta or {},
    })


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/chunks")
def list_chunks(kb_id: UUID, doc_id: UUID,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                db: Session = Depends(get_db),
                user: User | ViewTokenContext = Depends(get_current_user_or_view_token)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id).first()
    if not doc:
        raise not_found("文档不存在")
    q = db.query(Chunk).filter(Chunk.document_id == doc_id)
    total = q.count()
    items = q.order_by(Chunk.chunk_index) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return ok({
        "items": [
            schemas.ChunkOut(
                id=c.id,
                document_id=c.document_id,
                kb_id=c.kb_id,
                chunk_index=c.chunk_index,
                content=c.content,
                token_count=c.token_count,
                # 防御：metadata 列可能反序列化为非 dict（如 SQLAlchemy MetaData 对象）
                metadata=c.metadata if isinstance(c.metadata, dict) else {},
                created_at=c.created_at,
            ) for c in items
        ],
        "total": total, "page": page, "page_size": page_size,
    })


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/reparse")
def reparse_doc(kb_id: UUID, doc_id: UUID,
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id, is_deleted=False).first()
    if not doc:
        raise not_found("文档不存在")
    # 重置状态
    doc.status = "uploaded"
    doc.chunk_count = 0
    doc.error_message = None
    doc.version += 1
    # reparse 会换 full_text → 旧 PageIndex 树偏移失效，清掉；
    # 保留 index_type（v2：重建按该文档自身的 index_type 执行）
    meta = dict(doc.meta or {})
    if meta.get("index_type") == "pageindex":
        meta.pop("pageindex_tree", None)
        meta["pageindex_status"] = "none"
    elif "pageindex_tree" in meta:
        meta.pop("pageindex_tree", None)
        meta.pop("pageindex_status", None)
    doc.meta = meta
    # 显式生成 id 并 refresh 回填，确保 delay 时 id 可用
    task = ProcessTask(id=uuid.uuid4(), document_id=doc_id,
                       task_type="parse", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    parse_document_task.delay(str(doc_id), str(task.id))
    return ok({"task_id": task.id})


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/reindex")
def reindex_doc(kb_id: UUID, doc_id: UUID,
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """文档级重建索引（v2）：按该文档的 index_type 执行。

    - index_type=pageindex → 重建 PageIndex 树索引（build_pageindex_task）
    - index_type=embedding（默认/旧文档）→ 重建分块+向量索引（chunk_index_task）
    """
    from app.workers.tasks import build_pageindex_task, chunk_index_task
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id, is_deleted=False).first()
    if not doc:
        raise not_found("文档不存在")
    if not doc.full_text:
        raise param_error("文档尚未解析完成，无法重建索引")

    index_type = (doc.meta or {}).get("index_type", "embedding")

    if index_type == "pageindex":
        meta = dict(doc.meta or {})
        meta["pageindex_status"] = "building"
        doc.meta = meta
        # 显式生成 id：避免依赖 commit/refresh 回填
        task = ProcessTask(id=uuid.uuid4(), document_id=doc_id,
                           task_type="pageindex", status="pending")
        build_pageindex_task.delay(str(doc_id), str(task.id))
    else:
        # embedding 重建：复用 chunk_index 任务（full_text 已存在，仅重切块+重向量）
        task = ProcessTask(id=uuid.uuid4(), document_id=doc_id,
                           task_type="chunk_index", status="pending")
        chunk_index_task.delay(str(doc_id), str(task.id))

    db.add(task)
    db.commit()
    return ok({"task_id": task.id, "index_type": index_type})


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/pageindex/rebuild")
def rebuild_pageindex(kb_id: UUID, doc_id: UUID,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """手动触发 PageIndex 树索引重建（异步 Celery 任务）。

    v2：仅对 index_type=pageindex 的文档有效；其他文档返回 400 提示。
    """
    from app.workers.tasks import build_pageindex_task
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id, is_deleted=False).first()
    if not doc:
        raise not_found("文档不存在")
    if (doc.meta or {}).get("index_type") != "pageindex":
        raise param_error("该文档不是 PageIndex 索引方式，请使用“重建索引”按文档索引方式执行")
    if not doc.full_text:
        raise param_error("文档尚未解析完成，无法构建 PageIndex 树索引")
    # 标记 building
    meta = dict(doc.meta or {})
    meta["pageindex_status"] = "building"
    doc.meta = meta
    task = ProcessTask(document_id=doc_id, task_type="pageindex", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    build_pageindex_task.delay(str(doc_id), str(task.id))
    return ok({"task_id": task.id})


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
def delete_doc(kb_id: UUID, doc_id: UUID,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    doc = db.query(Document).filter_by(id=doc_id, kb_id=kb_id, is_deleted=False).first()
    if not doc:
        raise not_found("文档不存在")
    doc.is_deleted = True
    db.commit()
    # 异步清理 ES + MinIO
    cleanup_document_task.delay(str(doc_id), doc.minio_key, str(kb_id))
    return ok({})
