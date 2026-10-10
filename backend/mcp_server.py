#!/usr/bin/env python3
"""
kb-management MCP Server — 将知识库检索相关接口暴露为 MCP 工具。

启动: uvicorn mcp_server:app --host 0.0.0.0 --port 9100
或:   python mcp_server.py  (自动启动)

工具:
  1. list_knowledge_bases  — 列出所有知识库
  2. get_kb_details        — 获取知识库详情
  3. search_knowledge      — 混合检索（向量+全文+RRF）
  4. rag_query             — RAG 问答（LLM 生成带引用回答）
  5. list_documents        — 列出知识库的文档
  6. get_document_chunks   — 查看文档分块列表
"""
import json
import sys
import uuid
from typing import Optional

from loguru import logger

# 配置 loguru
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("/tmp/kb_mcp.log", level="INFO", rotation="10 MB", retention="3 days", enqueue=True)

# 导入项目模块（复用现有代码）
from mcp.server.mcpserver import MCPServer

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import KnowledgeBase, KbMember, Document, Chunk, User
from app.utils.es_client import es_client
from app.utils.ai_client import embedding_client
from app.services.rag_engine import rag_engine


# ============================================================
# 辅助函数
# ============================================================

def _resolve_kb(kb_id: str | None, name: str | None) -> KnowledgeBase:
    """通过 id 或 name 解析知识库。"""
    db = SessionLocal()
    try:
        if kb_id:
            kb = db.query(KnowledgeBase).filter(
                KnowledgeBase.id == uuid.UUID(kb_id),
                KnowledgeBase.is_deleted.is_(False),
            ).first()
        elif name:
            kb = db.query(KnowledgeBase).filter(
                KnowledgeBase.name.ilike(name),
                KnowledgeBase.is_deleted.is_(False),
            ).first()
        else:
            raise ValueError("必须提供 kb_id 或 name")
        if not kb:
            raise ValueError(f"知识库不存在: {kb_id or name}")
        return kb
    finally:
        db.close()


def _kb_to_dict(kb: KnowledgeBase, db, include_counts: bool = True) -> dict:
    """知识库 ORM → dict。"""
    data = {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "chunk_size": kb.chunk_size,
        "chunk_overlap": kb.chunk_overlap,
        "embedding_model": kb.embedding_model,
        "created_at": str(kb.created_at),
    }
    if include_counts:
        data["document_count"] = db.query(Document).filter(
            Document.kb_id == kb.id, Document.is_deleted.is_(False)).count()
        data["chunk_count"] = db.query(Chunk).filter(
            Chunk.kb_id == kb.id).count()
    return data


# ============================================================
# MCP Server
# ============================================================

mcp = MCPServer(
    name="kb-management",
    title="知识库管理系统 MCP Server",
    description="提供知识库列表、文档检索、混合搜索、RAG 问答等工具。",
    version="1.0.0",
)


# ---- 1. 列出知识库 ----

@mcp.tool()
def list_knowledge_bases(keyword: Optional[str] = None) -> str:
    """列出所有知识库。

    返回知识库列表，包含 id、名称、描述、文档数、分块数等信息。
    可通过 keyword 按名称模糊搜索。
    """
    db = SessionLocal()
    try:
        q = db.query(KnowledgeBase).filter(KnowledgeBase.is_deleted.is_(False))
        if keyword:
            q = q.filter(KnowledgeBase.name.ilike(f"%{keyword}%"))
        kbs = q.order_by(KnowledgeBase.created_at.desc()).all()

        items = []
        for kb in kbs:
            items.append(_kb_to_dict(kb, db))

        return json.dumps({
            "total": len(items),
            "items": items,
        }, ensure_ascii=False, indent=2)
    finally:
        db.close()


# ---- 2. 获取知识库详情 ----

@mcp.tool()
def get_kb_details(kb_id: Optional[str] = None, name: Optional[str] = None) -> str:
    """获取指定知识库的详细信息，包括成员列表、文档统计、分块统计。

    参数:
      kb_id: 知识库 UUID（与 name 二选一）
      name:  知识库名称（精确匹配，与 kb_id 二选一）
    """
    try:
        kb = _resolve_kb(kb_id, name)
    except (ValueError, uuid.UUIDError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    db = SessionLocal()
    try:
        data = _kb_to_dict(kb, db)

        # 成员列表
        members = []
        for m in kb.members:
            u = db.query(User).filter_by(id=m.user_id).first()
            members.append({
                "user_id": str(m.user_id),
                "username": u.username if u else None,
                "display_name": u.display_name if u else None,
                "role": m.role,
            })
        data["members"] = members

        # 文档列表（前 50 个）
        docs = (
            db.query(Document)
            .filter(Document.kb_id == kb.id, Document.is_deleted.is_(False))
            .order_by(Document.created_at.desc())
            .limit(50)
            .all()
        )
        data["documents"] = [
            {
                "id": str(d.id),
                "filename": d.filename,
                "file_type": d.file_type,
                "file_size": d.file_size,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "uploaded_at": str(d.uploaded_at),
                "error_message": d.error_message,
            }
            for d in docs
        ]
        data["document_count"] = len(data["documents"])

        return json.dumps(data, ensure_ascii=False, indent=2)
    finally:
        db.close()


# ---- 3. 混合检索 ----

@mcp.tool()
def search_knowledge(
    query: str,
    kb_id: Optional[str] = None,
    name: Optional[str] = None,
    mode: str = "hybrid",
    top_k: int = 10,
) -> str:
    """在知识库中执行混合检索（向量 kNN + BM25 全文 + RRF 融合）。

    参数:
      query:  搜索查询（自然语言或关键词）
      kb_id:  知识库 UUID（与 name 二选一，不传则搜索所有知识库）
      name:   知识库名称（与 kb_id 二选一）
      mode:   检索模式: hybrid(混合) / vector(纯向量) / keyword(纯关键词)，默认 hybrid
      top_k:  返回结果数量，默认 10，最大 100

    返回: 命中的文档片段列表，包含 filename、chunk_index、content、score、match_type。
    """
    # 解析知识库
    target_kb_ids: list[str] = []
    if kb_id or name:
        try:
            kb = _resolve_kb(kb_id, name)
            target_kb_ids = [str(kb.id)]
        except (ValueError, uuid.UUIDError) as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
    else:
        # 搜索所有知识库
        db = SessionLocal()
        try:
            kbs = db.query(KnowledgeBase.id).filter(
                KnowledgeBase.is_deleted.is_(False)).all()
            target_kb_ids = [str(kb_id) for (kb_id,) in kbs]
        finally:
            db.close()

    if not target_kb_ids:
        return json.dumps({"error": "没有可搜索的知识库"}, ensure_ascii=False)

    # 生成 query embedding（hybrid/vector 模式需要）
    query_vector = []
    if mode in ("hybrid", "vector"):
        try:
            query_vector = embedding_client.embed_one(query)
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to keyword: {e}")
            if mode == "vector":
                mode = "keyword"

    # 逐个知识库检索（多知识库时合并）
    all_hits = []
    total_ms = 0
    for kid in target_kb_ids:
        try:
            hits, took_ms = es_client.hybrid_search(
                kb_id=kid, query=query, query_vector=query_vector,
                mode=mode, top_k=top_k,
            )
            all_hits.extend(hits)
            total_ms += took_ms
        except Exception as e:
            logger.error(f"ES search failed for kb {kid}: {e}")

    # 按 score 排序 + 截断
    all_hits.sort(key=lambda x: x.get("score", 0), reverse=True)
    all_hits = all_hits[:top_k]

    items = [
        {
            "chunk_id": h["chunk_id"],
            "document_id": h["document_id"],
            "filename": h["filename"],
            "chunk_index": h["chunk_index"],
            "content": h["content"],
            "score": h.get("score", 0.0),
            "match_type": h.get("match_type", mode),
            "metadata": h.get("metadata", {}),
        }
        for h in all_hits
    ]

    return json.dumps({
        "query": query,
        "mode": mode,
        "total": len(items),
        "took_ms": total_ms,
        "items": items,
    }, ensure_ascii=False, indent=2)


# ---- 4. RAG 问答 ----

@mcp.tool()
def rag_query(
    question: str,
    kb_id: Optional[str] = None,
    name: Optional[str] = None,
    top_n: int = 5,
) -> str:
    """基于知识库的 RAG 问答：混合检索相关片段 + LLM 生成带引用的回答。

    参数:
      question: 用户问题（自然语言）
      kb_id:    知识库 UUID（与 name 二选一，不传则搜索所有知识库）
      name:     知识库名称（与 kb_id 二选一）
      top_n:    引用片段数量，默认 5

    返回: LLM 生成的完整回答（Markdown 格式）+ sources 来源引用列表。
    """
    # 解析知识库
    if kb_id or name:
        try:
            kb = _resolve_kb(kb_id, name)
        except (ValueError, uuid.UUIDError) as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
    else:
        db = SessionLocal()
        try:
            kb = db.query(KnowledgeBase).filter(
                KnowledgeBase.is_deleted.is_(False),
                KnowledgeBase.status == "active",
            ).order_by(KnowledgeBase.created_at.desc()).first()
        finally:
            db.close()
        if not kb:
            return json.dumps({"error": "没有可用的知识库"}, ensure_ascii=False)

    # 调用 RAG 引擎（非流式，收集完整回答）
    full_answer = ""
    sources = []
    error_msg = None

    for event in rag_engine.stream_answer(
        kb_id=str(kb.id),
        question=question,
        history=[],
        top_n=top_n,
    ):
        etype = event.get("type")
        if etype == "meta":
            sources = event.get("sources", [])
        elif etype == "token":
            full_answer += event["token"]
        elif etype == "done":
            full_answer = event.get("full", full_answer)
            if event.get("sources"):
                sources = event["sources"]
        elif etype == "error":
            error_msg = event.get("message", "未知错误")
            break

    if error_msg:
        return json.dumps({"error": error_msg}, ensure_ascii=False)

    return json.dumps({
        "question": question,
        "kb_name": kb.name,
        "answer": full_answer,
        "sources": sources,
    }, ensure_ascii=False, indent=2)


# ---- 5. 列出文档 ----

@mcp.tool()
def list_documents(
    kb_id: Optional[str] = None,
    name: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """列出指定知识库中的所有文档及其处理状态。

    参数:
      kb_id:  知识库 UUID（与 name 二选一）
      name:   知识库名称（与 kb_id 二选一）
      status: 文档状态过滤: uploaded/parsing/parsed/chunking/embedding/indexed/failed
    """
    try:
        kb = _resolve_kb(kb_id, name)
    except (ValueError, uuid.UUIDError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    db = SessionLocal()
    try:
        q = db.query(Document).filter(
            Document.kb_id == kb.id,
            Document.is_deleted.is_(False),
        )
        if status:
            q = q.filter(Document.status == status)
        docs = q.order_by(Document.created_at.desc()).all()

        items = [
            {
                "id": str(d.id),
                "filename": d.filename,
                "file_type": d.file_type,
                "file_size": d.file_size,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "error_message": d.error_message,
                "uploaded_at": str(d.uploaded_at),
                "indexed_at": str(d.indexed_at) if d.indexed_at else None,
            }
            for d in docs
        ]

        return json.dumps({
            "kb_id": str(kb.id),
            "kb_name": kb.name,
            "total": len(items),
            "items": items,
        }, ensure_ascii=False, indent=2)
    finally:
        db.close()


# ---- 6. 查看文档分块 ----

@mcp.tool()
def get_document_chunks(
    document_id: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """查看指定文档的分块列表。

    参数:
      document_id: 文档 UUID
      page:        页码，默认 1
      page_size:   每页数量，默认 20
    """
    db = SessionLocal()
    try:
        try:
            doc_uuid = uuid.UUID(document_id)
        except uuid.UUIDError:
            return json.dumps({"error": f"无效的 document_id: {document_id}"}, ensure_ascii=False)

        doc = db.query(Document).filter(
            Document.id == doc_uuid,
            Document.is_deleted.is_(False),
        ).first()
        if not doc:
            return json.dumps({"error": "文档不存在"}, ensure_ascii=False)

        total = db.query(Chunk).filter(Chunk.document_id == doc_uuid).count()
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == doc_uuid)
            .order_by(Chunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        items = [
            {
                "id": str(c.id),
                "chunk_index": c.chunk_index,
                "content": c.content,
                "token_count": c.token_count,
                "metadata": c.chunk_meta,
            }
            for c in chunks
        ]

        return json.dumps({
            "document_id": str(doc.id),
            "filename": doc.filename,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }, ensure_ascii=False, indent=2)
    finally:
        db.close()


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    logger.info("kb-management MCP Server starting on 0.0.0.0:9100")
    uvicorn.run(
        "mcp_server:streamable_app",
        host="0.0.0.0",
        port=9100,
        log_level="info",
    )


# 供 uvicorn 直接加载的 Starlette app
streamable_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
)
