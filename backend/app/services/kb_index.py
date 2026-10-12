"""KB 索引构成统计 —— `auto`（智能）检索的路由依据。

规格：`01-product/PRD-AUTO-RETRIEVAL.md` §F2
约束：单次 SQL 聚合，**不逐文档查询**、**不跨请求缓存**（每次请求实时统计，
      与 R2 一致：文档刚上传/刚建完树后立刻提问必须路由正确）。
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def kb_index_composition(db: Session, kb_id: UUID | str) -> dict:
    """统计 KB 下两类"可检索文档"的数量。

    - embedding_docs：`is_deleted=false AND kb_id=? AND status='indexed'
      AND COALESCE(meta->>'index_type','embedding')='embedding'`
      （历史无 index_type 的文档按 embedding 兜底，与 `workers/tasks.py` 分流一致）
    - pageindex_docs：`is_deleted=false AND kb_id=? AND meta->>'index_type'='pageindex'
      AND meta->>'pageindex_status' IN ('ok','degraded')`

    返回：`{"embedding_docs": int, "pageindex_docs": int}`
    """
    row = db.execute(text("""
        SELECT
            COUNT(*) FILTER (
                WHERE status = 'indexed'
                  AND COALESCE(meta->>'index_type', 'embedding') = 'embedding'
            ) AS embedding_docs,
            COUNT(*) FILTER (
                WHERE meta->>'index_type' = 'pageindex'
                  AND meta->>'pageindex_status' IN ('ok', 'degraded')
            ) AS pageindex_docs
        FROM document
        WHERE is_deleted = false AND kb_id = :kb_id
    """), {"kb_id": str(kb_id)}).one()
    return {"embedding_docs": int(row[0] or 0), "pageindex_docs": int(row[1] or 0)}
