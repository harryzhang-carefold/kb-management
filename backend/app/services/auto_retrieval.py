"""`auto`（智能）检索：按 KB 索引构成自动路由 + 混合库联邦检索合并。

规格：`01-product/PRD-AUTO-RETRIEVAL.md`（F3 路由 / F4 合并 / F5 单腿异常 / F6 文案）
决策：`01-product/PRODUCT_DECISIONS.md` §PD-001

红线（不改）：
- `es_client.hybrid_search` 内部实现、`pageindex_engine` 内部实现；
- 任何**显式** mode（hybrid/vector/keyword/pageindex）分支的行为；
- 显式 `mode=pageindex` 命中 0 不回退 ES（`api/search.py` 原样保留）。

实现要点：
- 单腿路由（仅 embedding / 仅 pageindex）**完全复用**对应显式模式的路径与分数，
  不归一化、不改排序 → 与显式模式"等价"（F3）。
- 两腿都执行（混合库）时才做 F4 合并：各腿按自身最高分归一化 → 降序（同分
  pageindex 腿优先）→ 去重 → 截断。分数归一化**仅用于排序/展示**，
  两腿量纲不同（ES RRF ≈1/60 vs pageindex LLM relevance 0–1），不可当绝对阈值用。
"""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger

from app.services.kb_index import kb_index_composition
from app.utils.ai_client import embedding_client
from app.utils.es_client import es_client

# ---- F6 文案（逐字，禁止改写）----
MSG_NO_DOC = "本知识库暂无可检索的文档。请先上传文档并等待索引完成。"
MSG_ES_EMPTY = "未在向量索引中检索到相关内容。可尝试换用「关键词」模式或换一种问法。"
MSG_PAGEINDEX_EMPTY = "未在 PageIndex 索引中检索到相关内容。请换一种问法（树索引对文档标题与小节更敏感）。"
MSG_BOTH_EMPTY = "未在知识库中检索到相关内容，请换一种问法或补充资料。"
MSG_PAGEINDEX_DEGRADED = "PageIndex 检索暂不可用，本次仅基于向量索引回答。"

LEG_ES = "es"
LEG_PAGEINDEX = "pageindex"


def _dedup_key(hit: dict) -> tuple:
    """去重键：`(document_id, chunk_index)`（F4）。

    pageindex 命中的 `chunk_index` 是"文档内首个 chunk 的溯源锚点"（整篇文档同值），
    因此再带上 `metadata.node_id` 区分同一文档的不同节点；ES 命中无 node_id →
    退化为规格中的 `(document_id, chunk_index)` 二键。
    """
    meta = hit.get("metadata") or {}
    return (str(hit.get("document_id")), int(hit.get("chunk_index") or 0),
            str(meta.get("node_id") or ""))


def _es_leg(kb_id: str, query: str, top_k: int,
            filters: Optional[dict] = None) -> tuple[list[dict], int]:
    """ES 混合腿 —— 与显式 `mode=hybrid` 同路径。

    embedding 不可用时沿用现状：query_vector 置空 → es_client 内部退化为纯 BM25，
    不新增分支、不报错（与 `api/search.py` 的 hybrid 分支、
    `services/rag_engine.py` 原有 hybrid 分支一致）。
    """
    query_vector: list[float] = []
    try:
        query_vector = embedding_client.embed_one(query)
    except Exception as e:  # noqa: BLE001 —— 沿用现状：静默退化为关键词检索
        logger.warning(f"auto/es leg: embedding 不可用，退化为关键词检索: {e}")
    hits, took_ms = es_client.hybrid_search(
        kb_id=kb_id, query=query, query_vector=query_vector,
        mode="hybrid", top_k=top_k, filters=filters,
    )
    for h in hits:
        h["metadata"] = {**(h.get("metadata") or {}), "leg": LEG_ES}
    return hits, took_ms


def _pageindex_leg(kb_id: str, query: str, top_n: int,
                   filters: Optional[dict] = None, db=None) -> tuple[list[dict], int, Optional[str]]:
    """pageindex 树索引腿。`pageindex_engine.retrieve` 内部不捕获异常时返回
    `extra['error']`，两者都视为"该腿异常"（F5）。"""
    from app.services.pageindex_engine import retrieve as pageindex_retrieve
    hits, took_ms, extra = pageindex_retrieve(
        kb_id, query, top_n, filters=filters, db=db)
    err = (extra or {}).get("error")
    for h in hits:
        h["metadata"] = {**(h.get("metadata") or {}), "leg": LEG_PAGEINDEX}
    return hits, took_ms, err


def _merge_two_legs(legs: list[tuple[str, list[dict]]], limit: int) -> list[dict]:
    """F4 合并：各腿按自身最高分归一化 → 降序（同分 pageindex 腿优先）→
    去重（保留高分）→ 截断到 `limit`。"""
    ranked: list[tuple[float, int, int, str, dict]] = []
    for leg, hits in legs:
        if not hits:
            continue
        max_score = max(float(h.get("score") or 0.0) for h in hits)
        for rank, h in enumerate(hits):
            raw = float(h.get("score") or 0.0)
            norm = (raw / max_score) if max_score > 0 else 0.0
            # 排序键：归一化分降序 → 同分 pageindex(0) 优先 → 腿内原顺序
            ranked.append((norm, 0 if leg == LEG_PAGEINDEX else 1, rank, leg, h))
    ranked.sort(key=lambda x: (-x[0], x[1], x[2]))

    out: list[dict] = []
    seen: set[tuple] = set()
    for norm, _prio, _rank, _leg, h in ranked:
        key = _dedup_key(h)
        if key in seen:
            continue
        seen.add(key)
        item = dict(h)
        item["score"] = round(norm, 6)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _single_leg(hits: list[dict], limit: int) -> list[dict]:
    """单腿 auto：分数保持该腿原值（**不归一化**），与对应显式模式等价（F3）。"""
    out: list[dict] = []
    seen: set[tuple] = set()
    for h in hits:
        key = _dedup_key(h)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(h))
        if len(out) >= limit:
            break
    return out


def _route_of(embedding_docs: int, pageindex_docs: int) -> str:
    if embedding_docs and pageindex_docs:
        return "both"
    if embedding_docs:
        return "es"
    if pageindex_docs:
        return "pageindex"
    return "none"


def run_auto(db, kb_id: str, query: str, limit: int,
             es_top_k: Optional[int] = None,
             filters: Optional[dict] = None) -> dict:
    """`auto` 路由执行体（search 与 chat 共用）。

    - `limit`：最终返回条数（search=top_k / chat=top_n）；
    - `es_top_k`：ES 腿取数条数，默认 = `limit`（chat 传 `settings.rag_top_k`
      以与既有 hybrid 问答路径完全一致）。

    返回 dict：
      `hits`（list[dict]，字段同 SearchResultItem 对应 hit）、`took_ms`（实际墙钟）、
      `route`（es|pageindex|both|none）、`composition`、`message`（F6 文案或 None）、
      `degraded`（["pageindex"] 或 []）。

    异常：两腿都异常时抛出首个底层异常（沿用现有错误路径）。
    """
    t0 = time.time()
    own_session = db is None
    if own_session:
        from app.core.database import SessionLocal
        db = SessionLocal()
    try:
        comp = kb_index_composition(db, kb_id)
        route = _route_of(comp["embedding_docs"], comp["pageindex_docs"])

        if route == "none":
            took_ms = int((time.time() - t0) * 1000)
            logger.info(f"auto_route=none kb_id={kb_id} composition={comp} "
                        f"degraded=[] took_ms={took_ms} total=0")
            return {"hits": [], "took_ms": took_ms, "route": route,
                    "composition": comp, "message": MSG_NO_DOC, "degraded": []}

        legs: list[tuple[str, list[dict]]] = []
        legs_ms = 0
        degraded: list[str] = []
        first_exc: Optional[Exception] = None

        if comp["embedding_docs"]:
            try:
                hits, ms = _es_leg(kb_id, query, es_top_k or limit, filters)
                legs.append((LEG_ES, hits))
                legs_ms += ms
            except Exception as e:  # noqa: BLE001
                first_exc = first_exc or e
                logger.error(f"auto_route={route} kb_id={kb_id} es leg failed: {e}")

        if comp["pageindex_docs"]:
            # F5：pageindex 腿异常不中断，返回 ES 腿结果并标记降级
            try:
                hits, ms, err = _pageindex_leg(kb_id, query, limit, filters, db)
                if err:
                    degraded.append(LEG_PAGEINDEX)
                    logger.error(f"auto_route={route} kb_id={kb_id} pageindex leg error: {err}")
                else:
                    legs.append((LEG_PAGEINDEX, hits))
                    legs_ms += ms
            except Exception as e:  # noqa: BLE001
                degraded.append(LEG_PAGEINDEX)
                logger.error(f"auto_route={route} kb_id={kb_id} pageindex leg failed: {e}")

        if not legs:
            # 两腿都异常 → 沿用现有错误路径
            if first_exc:
                raise first_exc
            raise RuntimeError("auto 检索两路均不可用")

        if len(legs) >= 2:
            hits = _merge_two_legs(legs, limit)
        else:
            hits = _single_leg(legs[0][1], limit)

        took_ms = int((time.time() - t0) * 1000)
        message: Optional[str] = None
        if degraded:
            message = MSG_PAGEINDEX_DEGRADED
        elif not hits:
            message = {"both": MSG_BOTH_EMPTY, "es": MSG_ES_EMPTY,
                       "pageindex": MSG_PAGEINDEX_EMPTY}[route]

        logger.info(f"auto_route={route} kb_id={kb_id} composition={comp} "
                    f"degraded={degraded} took_ms={took_ms} legs_ms={legs_ms} "
                    f"total={len(hits)}")
        return {"hits": hits, "took_ms": took_ms, "route": route,
                "composition": comp, "message": message, "degraded": degraded}
    finally:
        if own_session:
            db.close()
