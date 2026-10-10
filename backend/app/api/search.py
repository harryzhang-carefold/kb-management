"""检索路由 /knowledge-bases/{kb_id}/search"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.responses import ok, not_found
from app.core.database import get_db
from app.schemas import schemas
from app.models import *
from app.api.deps import get_current_user, require_kb_access
from app.utils.es_client import es_client
from app.utils.ai_client import embedding_client

router = APIRouter(tags=["检索"])


@router.post("/knowledge-bases/{kb_id}/search")
def search(kb_id: UUID, req: schemas.SearchReq,
           db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)

    # PageIndex 检索：跳过 embedding，直接走 pageindex_engine（LLM 推理）
    if req.mode == "pageindex":
        from app.services.pageindex_engine import retrieve as pageindex_retrieve
        hits, took_ms, extra = pageindex_retrieve(
            str(kb_id), req.query, req.top_k, filters=req.filters,
        )
        items = [
            schemas.SearchResultItem(
                chunk_id=h["chunk_id"], document_id=h["document_id"],
                filename=h["filename"], chunk_index=h["chunk_index"],
                content=h["content"], score=h.get("score", 0.0),
                match_type=h.get("match_type", "pageindex"),
                metadata=h.get("metadata", {}),
            ) for h in hits
        ]
        payload = {"items": items, "total": len(items), "took_ms": took_ms}
        # v2 需求 4：无 pageindex 索引文档时附带提示（不静默回退）
        if extra and extra.get("message"):
            payload["message"] = extra["message"]
        if extra and extra.get("error"):
            payload["error"] = extra["error"]
        return ok(payload)

    # 向量检索需要 query embedding
    query_vector = []
    if req.mode in ("hybrid", "vector"):
        try:
            query_vector = embedding_client.embed_one(req.query)
        except Exception:
            # embedding 不可用时退化为纯关键词
            query_vector = []
            if req.mode == "vector":
                req.mode = "keyword"

    hits, took_ms = es_client.hybrid_search(
        kb_id=str(kb_id), query=req.query, query_vector=query_vector,
        mode=req.mode, top_k=req.top_k, filters=req.filters,
    )

    items = [
        schemas.SearchResultItem(
            chunk_id=h["chunk_id"], document_id=h["document_id"],
            filename=h["filename"], chunk_index=h["chunk_index"],
            content=h["content"], score=h.get("score", 0.0),
            match_type=h.get("match_type", "hybrid"),
            metadata=h.get("metadata", {}),
        ) for h in hits
    ]
    return ok({"items": items, "total": len(items), "took_ms": took_ms})
