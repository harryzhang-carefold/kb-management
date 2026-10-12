#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""db_probe.py — kb-management 文档索引元数据【只读】探针（VI-PI 用例 5 用）

用途：直接读库核对 document.meta.index_type / pageindex_status，作为 HTTP 之外的
      独立证据面（不采信接口自述）。全程只执行 SELECT，不写库、不改数据。

运行（必须用仓库自带 venv）：
    cd /home/harry.zhang/kb-management
    backend/.venv/bin/python 03-testing/curl/lib/db_probe.py <mode> [args]

模式：
    dist                  全量文档 index_type 分布（含状态、pageindex_status 分布）
    doc   <document_id>   单文档 meta 摘要（不含全文、不含整棵树）
    by-kb                 按知识库聚合（每库 pageindex / embedding / 无标记 计数）
    legacy                列出"历史无 index_type"文档（兜底路径证据）

可选参数：
    --kb <kb_id>          仅看某知识库（dist / legacy 模式）
    --json                以 JSON 输出（默认人类可读）
    --limit N             列表类输出上限，默认 50

只读保证：会话起始即 SET TRANSACTION READ ONLY；任何写操作会被 PG 拒绝。
首次编写：2026-10-12（PI-V1，卡 t_fa5d836a），仅脚手架，未做任何用例判定。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# --- 定位 backend/ 并复用应用的 database.py ---
_THIS = Path(__file__).resolve()
_REPO = _THIS.parents[3]                      # .../kb-management
_BACKEND = _REPO / "backend"
if not (_BACKEND / "app" / "core" / "database.py").exists():
    sys.exit(f"[db_probe] 找不到 {_BACKEND}/app/core/database.py，请确认仓库路径")
sys.path.insert(0, str(_BACKEND))
os.chdir(_BACKEND)                            # 与 uvicorn 工作目录一致，保证 infra/.env 相对定位正确

from sqlalchemy import text                   # noqa: E402
from app.core.database import SessionLocal, engine    # noqa: E402

# 静默 SQL echo（.env DEBUG=true 时 engine.echo=True 会刷屏），探针输出只留结论
engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def _session():
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
    except Exception:
        db.rollback()
    return db


IT_EXPR = "COALESCE(d.meta->>'index_type', '<none>')"


def q_dist(db, kb_id: str | None):
    sql = f"""
        SELECT {IT_EXPR} AS index_type,
               COALESCE(d.meta->>'pageindex_status', '-') AS pageindex_status,
               d.status, COUNT(*) AS cnt
        FROM document d
        WHERE d.is_deleted = false
          {"AND d.kb_id = :kb" if kb_id else ""}
        GROUP BY 1, 2, 3
        ORDER BY cnt DESC
    """
    rows = db.execute(text(sql), {"kb": kb_id} if kb_id else {}).mappings().all()
    total = sum(r["cnt"] for r in rows)
    return {"scope_kb": kb_id or "*", "total_docs": total, "rows": [dict(r) for r in rows]}


def q_doc(db, doc_id: str):
    sql = """
        SELECT d.id, d.kb_id, kb.name AS kb_name, d.filename, d.file_type, d.file_size,
               d.status, d.chunk_count, d.is_deleted, d.error_message,
               d.uploaded_at, d.indexed_at,
               d.meta->>'index_type' AS index_type,
               d.meta->>'pageindex_status' AS pageindex_status,
               jsonb_typeof(d.meta->'pageindex_tree') AS tree_type,
               (d.meta ? 'pageindex_tree') AS has_tree,
               (SELECT COUNT(*) FROM chunk c WHERE c.document_id = d.id) AS chunk_rows,
               d.meta AS meta_full
        FROM document d LEFT JOIN knowledge_base kb ON kb.id = d.kb_id
        WHERE d.id::text = :id OR d.id::text LIKE :id || '%'
        LIMIT 5
    """
    rows = db.execute(text(sql), {"id": doc_id}).mappings().all()
    out = []
    for r in rows:
        r = dict(r)
        meta = r.pop("meta_full") or {}
        tree = meta.get("pageindex_tree")
        node_count = None
        if isinstance(tree, dict):
            if isinstance(tree.get("node_count"), int):
                node_count = tree["node_count"]          # 建树时自报的节点数
            else:
                def _count(n):
                    if not isinstance(n, dict):
                        return 0
                    return 1 + sum(_count(c) for c in (n.get("children") or []))
                root = tree.get("root")
                if isinstance(root, dict):
                    node_count = _count(root)            # 兜底：按 root 子树实际计数
        r["meta_keys"] = sorted(meta.keys())
        r["pageindex_tree"] = {
            "present": "pageindex_tree" in meta,
            "type": type(tree).__name__,
            "top_level_keys": sorted(tree.keys()) if isinstance(tree, dict) else None,
            "node_count": node_count,
            "note": "只统计结构，不回传整棵树",
        }
        r["meta_other"] = {k: v for k, v in meta.items() if k != "pageindex_tree"}
        out.append(r)
    return out


def q_by_kb(db):
    sql = f"""
        SELECT d.kb_id, kb.name AS kb_name,
               COUNT(*) AS docs,
               SUM(CASE WHEN {IT_EXPR} = 'pageindex' THEN 1 ELSE 0 END) AS cnt_pageindex,
               SUM(CASE WHEN {IT_EXPR} = 'embedding' THEN 1 ELSE 0 END) AS cnt_embedding,
               SUM(CASE WHEN {IT_EXPR} = '<none>'  THEN 1 ELSE 0 END) AS cnt_none
        FROM document d LEFT JOIN knowledge_base kb ON kb.id = d.kb_id
        WHERE d.is_deleted = false
        GROUP BY 1, 2
        ORDER BY docs DESC
    """
    return [dict(r) for r in db.execute(text(sql)).mappings().all()]


def q_legacy(db, kb_id: str | None, limit: int):
    sql = f"""
        SELECT d.id, d.kb_id, d.filename, d.status, d.chunk_count,
               COALESCE(d.meta->>'index_type', '<none>') AS index_type, d.uploaded_at
        FROM document d
        WHERE d.is_deleted = false AND d.meta->>'index_type' IS NULL
          {"AND d.kb_id = :kb" if kb_id else ""}
        ORDER BY d.uploaded_at DESC
        LIMIT :lim
    """
    p = {"lim": limit}
    if kb_id:
        p["kb"] = kb_id
    return [dict(r) for r in db.execute(text(sql), p).mappings().all()]


def _default(o):
    return str(o)


def main():
    ap = argparse.ArgumentParser(description="kb-management 文档索引元数据只读探针")
    ap.add_argument("mode", choices=["dist", "doc", "by-kb", "legacy"])
    ap.add_argument("arg", nargs="?", help="doc 模式的 document_id（可前缀）")
    ap.add_argument("--kb", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args()

    db = _session()
    try:
        if a.mode == "dist":
            data = q_dist(db, a.kb)
        elif a.mode == "doc":
            if not a.arg:
                sys.exit("[db_probe] doc 模式需要 document_id")
            data = q_doc(db, a.arg)
        elif a.mode == "by-kb":
            data = q_by_kb(db)
        else:
            data = q_legacy(db, a.kb, a.limit)
    finally:
        db.close()

    if a.json:
        print(json.dumps(data, ensure_ascii=False, default=_default, indent=2))
        return

    print(f"# db_probe mode={a.mode} scope_kb={a.kb or '*'} (read-only)")
    if a.mode == "dist":
        print(f"total_docs={data['total_docs']}")
        print(f"{'index_type':<12}{'pageindex_status':<18}{'status':<12}{'count':>6}")
        for r in data["rows"]:
            print(f"{r['index_type']:<12}{r['pageindex_status']:<18}{r['status']:<12}{r['cnt']:>6}")
    elif a.mode == "doc":
        if not data:
            print("(no document matched)")
        for r in data:
            print(f"id={r['id']} kb={r['kb_id']} ({r['kb_name']}) file={r['filename']}")
            print(f"  status={r['status']} is_deleted={r['is_deleted']} file_type={r['file_type']} "
                  f"file_size={r['file_size']}")
            print(f"  index_type={r['index_type']} pageindex_status={r['pageindex_status']} "
                  f"chunk_count={r['chunk_count']} chunk_rows={r['chunk_rows']}")
            print(f"  indexed_at={r['indexed_at']} uploaded_at={r['uploaded_at']}")
            print(f"  meta_keys={r['meta_keys']}")
            print(f"  tree={r['pageindex_tree']}")
            print(f"  meta_other={json.dumps(r['meta_other'], ensure_ascii=False, default=_default)}")
            if r["error_message"]:
                print(f"  error_message={r['error_message']}")
    elif a.mode == "by-kb":
        print(f"{'kb_id':<38}{'docs':>5}{'pageindex':>11}{'embedding':>11}{'none':>6}  name")
        for r in data:
            print(f"{str(r['kb_id']):<38}{r['docs']:>5}{r['cnt_pageindex']:>11}"
                  f"{r['cnt_embedding']:>11}{r['cnt_none']:>6}  {r['kb_name']}")
    else:
        print(f"legacy_no_index_type rows={len(data)} (limit={a.limit})")
        for r in data:
            print(f"  {r['id']} kb={r['kb_id']} status={r['status']} chunks={r['chunk_count']} "
                  f"file={r['filename']} uploaded_at={r['uploaded_at']}")


if __name__ == "__main__":
    main()
