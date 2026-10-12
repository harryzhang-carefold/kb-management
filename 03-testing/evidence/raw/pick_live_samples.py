#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pick_live_samples.py — 只读：列出"KB 未删除"的存量样本候选（供用例 5 选择行为性操作对象）

用法:
    backend/.venv/bin/python 03-testing/evidence/raw/pick_live_samples.py [index_type]
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

REPO = Path("/home/harry.zhang/kb-management")
BACK = REPO / "backend"
sys.path.insert(0, str(BACK))
os.chdir(BACK)

from sqlalchemy import text  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402

engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

it = sys.argv[1] if len(sys.argv) > 1 else "pageindex"

db = SessionLocal()
try:
    db.execute(text("SET TRANSACTION READ ONLY"))
    rows = db.execute(text("""
        SELECT kb.id::text AS kb_id, kb.name, kb.is_deleted AS kb_deleted,
               d.id::text AS doc_id, d.filename, d.status, d.chunk_count, d.uploaded_at,
               d.meta->>'index_type' AS it, d.meta->>'pageindex_status' AS pis,
               (d.meta ? 'pageindex_tree') AS has_tree
        FROM document d JOIN knowledge_base kb ON kb.id = d.kb_id
        WHERE d.is_deleted = false AND kb.is_deleted = false
          AND d.meta->>'index_type' = :it
          AND d.uploaded_at <= '2026-10-12T03:16:05Z'
        ORDER BY d.uploaded_at
    """), {"it": it}).mappings().all()
    print(f"# live-KB legacy-scope docs with index_type={it}: {len(rows)}")
    for r in rows:
        print(f"{r['doc_id'][:8]} kb={r['kb_id'][:8]} tree={r['has_tree']} pis={r['pis']} "
              f"st={r['status']} chunks={r['chunk_count']} {str(r['uploaded_at'])[:19]} "
              f"kbname={r['name'][:26]} f={r['filename'][:22]}")
finally:
    db.close()
