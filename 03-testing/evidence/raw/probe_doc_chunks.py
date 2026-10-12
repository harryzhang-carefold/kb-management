#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""probe_doc_chunks.py — 只读：列出指定 KB 内文档的分块概况（供用例 5 选择存量样本 + 取检索锚点）

只读保证：SET TRANSACTION READ ONLY；仅 SELECT。不打印完整全文，只给每篇前 2 个分块的
        前 160 字符（作为检索 query 的构造依据）。
用法:
    backend/.venv/bin/python 03-testing/evidence/raw/probe_doc_chunks.py <kb_id> [--docs id1,id2]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parents[3]
_BACKEND = _REPO / "backend"
sys.path.insert(0, str(_BACKEND))
os.chdir(_BACKEND)

from sqlalchemy import text  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402

engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kb_id")
    ap.add_argument("--docs", default=None)
    a = ap.parse_args()

    db = SessionLocal()
    try:
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
        except Exception:
            db.rollback()
        ids = [x.strip() for x in a.docs.split(",")] if a.docs else None
        sql = text("""
            SELECT d.id::text AS doc_id, d.filename, d.status, d.chunk_count,
                   d.meta->>'index_type' AS index_type,
                   d.meta->>'pageindex_status' AS pageindex_status,
                   (d.meta ? 'pageindex_tree') AS has_tree,
                   d.uploaded_at
            FROM document d
            WHERE d.kb_id::text = :kb AND d.is_deleted = false
            ORDER BY d.uploaded_at
        """)
        docs = [dict(r) for r in db.execute(sql, {"kb": a.kb_id}).mappings().all()]
        for d in docs:
            if ids and not any(d["doc_id"].startswith(i) for i in ids):
                continue
            print(f"DOC {d['doc_id']} file={d['filename']} status={d['status']} "
                  f"chunk_count={d['chunk_count']} index_type={d['index_type']} "
                  f"pi_status={d['pageindex_status']} has_tree={d['has_tree']} up={d['uploaded_at']}")
            ctot = db.execute(text(
                "SELECT COUNT(*) FROM chunk WHERE document_id::text = :id"
            ), {"id": d["doc_id"]}).scalar()
            crows = db.execute(text("""
                SELECT chunk_index, left(content, 160) AS head, length(content) AS len
                FROM chunk WHERE document_id::text = :id ORDER BY chunk_index LIMIT 2
            """), {"id": d["doc_id"]}).mappings().all()
            print(f"  chunk_rows_total={ctot}")
            for c in crows:
                print(f"  [c{c['chunk_index']} len={c['len']}] {c['head']!r}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
