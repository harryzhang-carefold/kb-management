"""知识库路由 /knowledge-bases"""
from fastapi import APIRouter, Depends, Query, UploadFile, File
from sqlalchemy.orm import Session
from uuid import UUID
import uuid as _uuid
import os

from app.core.config import settings
from app.core.database import get_db
from app.core.responses import ok, not_found, param_error
from app.schemas import schemas
from app.models import *
from app.api.deps import get_current_user, require_kb_access
from app.workers.tasks import parse_document_task, cleanup_kb_task
from app.utils.doc_parser import detect_file_type
from app.utils.minio_client import minio_client
from app.utils.es_client import es_client

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


def _count_docs(db: Session, kb_id: UUID) -> int:
    return db.query(Document).filter(
        Document.kb_id == kb_id, Document.is_deleted.is_(False)).count()


def _count_chunks(db: Session, kb_id: UUID) -> int:
    return db.query(Chunk).filter(Chunk.kb_id == kb_id).count()


def _kb_detail_out(kb: KnowledgeBase, db: Session) -> schemas.KbDetailOut:
    members = []
    for m in kb.members:
        u = db.query(User).filter_by(id=m.user_id).first()
        members.append(schemas.KbMemberOut(
            id=m.id, kb_id=m.kb_id, user_id=m.user_id, role=m.role,
            created_at=m.created_at,
            username=u.username if u else None,
            email=u.email if u else None,
            display_name=u.display_name if u else None,
        ))
    base = schemas.KbOut.model_validate(kb)
    return schemas.KbDetailOut(
        **base.model_dump(),
        document_count=_count_docs(db, kb.id),
        chunk_count=_count_chunks(db, kb.id),
        members=members,
    )


@router.get("")
def list_kbs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             status: str | None = None, keyword: str | None = None,
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    q = db.query(KnowledgeBase).filter(KnowledgeBase.is_deleted.is_(False))
    # 非 admin 只能看自己有权限的
    if user.role != "admin":
        q = q.filter(
            (KnowledgeBase.owner_id == user.id) |
            (KnowledgeBase.id.in_(
                db.query(KbMember.kb_id).filter(KbMember.user_id == user.id)))
        )
    if status:
        q = q.filter(KnowledgeBase.status == status)
    if keyword:
        q = q.filter(KnowledgeBase.name.ilike(f"%{keyword}%"))
    total = q.count()
    items = q.order_by(KnowledgeBase.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return ok({
        "items": [schemas.KbOut.model_validate(k) for k in items],
        "total": total, "page": page, "page_size": page_size,
    })


@router.post("")
def create_kb(req: schemas.KbCreateReq,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    kb = KnowledgeBase(
        owner_id=user.id, name=req.name, description=req.description or "",
        chunk_size=req.chunk_size, chunk_overlap=req.chunk_overlap,
        embedding_dim=req.embedding_dim, embedding_model=req.embedding_model,
    )
    db.add(kb)
    db.flush()
    # owner 自动成为 member
    db.add(KbMember(kb_id=kb.id, user_id=user.id, role="owner"))
    # 添加其他成员
    for uid in req.member_user_ids:
        u = db.query(User).filter_by(id=uid).first()
        if u:
            role = req.member_roles.get(str(uid), "viewer")
            db.add(KbMember(kb_id=kb.id, user_id=uid, role=role))
    db.commit()
    db.refresh(kb)
    return ok(_kb_detail_out(kb, db))


@router.get("/{kb_id}")
def get_kb(kb_id: UUID, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    return ok(_kb_detail_out(kb, db))


@router.get("/{kb_id}/index-stats")
def kb_index_stats(kb_id: UUID, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """KB 索引构成统计（只读，鉴权同 KB 详情）。供前端/运维核对 auto 路由依据。"""
    from app.services.kb_index import kb_index_composition
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    comp = kb_index_composition(db, kb_id)
    return ok({
        "embedding_docs": comp["embedding_docs"],
        "pageindex_docs": comp["pageindex_docs"],
        "total_indexed": comp["embedding_docs"] + comp["pageindex_docs"],
    })


@router.put("/{kb_id}")
def update_kb(kb_id: UUID, req: schemas.KbUpdateReq,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            setattr(kb, k, v)
    db.commit()
    db.refresh(kb)
    return ok(_kb_detail_out(kb, db))


@router.delete("/{kb_id}")
def delete_kb(kb_id: UUID, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="owner")
    kb.is_deleted = True
    db.commit()
    # 异步清理 ES + MinIO
    cleanup_kb_task.delay(str(kb_id))
    return ok({})


# ============================================================
# 成员管理
# ============================================================
@router.get("/{kb_id}/members")
def list_members(kb_id: UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    members = []
    for m in kb.members:
        u = db.query(User).filter_by(id=m.user_id).first()
        members.append(schemas.KbMemberOut(
            id=m.id, kb_id=m.kb_id, user_id=m.user_id, role=m.role,
            created_at=m.created_at,
            username=u.username if u else None,
            email=u.email if u else None,
            display_name=u.display_name if u else None,
        ))
    return ok({"items": members, "total": len(members)})


@router.post("/{kb_id}/members")
def add_member(kb_id: UUID, req: schemas.KbMemberReq,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    if db.query(KbMember).filter_by(kb_id=kb_id, user_id=req.user_id).first():
        raise param_error("成员已存在")
    m = KbMember(kb_id=kb_id, user_id=req.user_id, role=req.role)
    db.add(m)
    db.commit()
    return ok(schemas.KbMemberOut.model_validate(m))


@router.put("/{kb_id}/members/{user_id}")
def update_member(kb_id: UUID, user_id: UUID, req: schemas.KbMemberUpdateReq,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    m = db.query(KbMember).filter_by(kb_id=kb_id, user_id=user_id).first()
    if not m:
        raise not_found("成员不存在")
    if m.role == "owner":
        raise param_error("不能修改 owner 角色")
    m.role = req.role
    db.commit()
    return ok(schemas.KbMemberOut.model_validate(m))


@router.delete("/{kb_id}/members/{user_id}")
def remove_member(kb_id: UUID, user_id: UUID,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb, min_role="editor")
    m = db.query(KbMember).filter_by(kb_id=kb_id, user_id=user_id).first()
    if not m:
        raise not_found("成员不存在")
    if m.role == "owner":
        raise param_error("不能移除 owner")
    db.delete(m)
    db.commit()
    return ok({})
