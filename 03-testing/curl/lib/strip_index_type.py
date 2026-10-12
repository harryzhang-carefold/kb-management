#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""strip_index_type.py — 【写库·严格限定】把**指定单篇文档** meta.index_type 键删除

用途（VI-PI-3 用例 5 步骤 6）：真实存量中"无 index_type 的老文档"为 0 篇（只读审计证明见
evidence/PI-V3_legacy_audit.json → index_type_dist_all 无 <none>），因此必须**显式标注为模拟用例**：
在自建测试 KB 的文档上人工去掉 meta.index_type，复现历史老文档形态，再验证兜底分支。

安全约束（脚本强制）：
  * 必须同时给 --doc <id> 与 --expect-kb <kb_id>，并校验该文档确实属于该 KB；
  * 只允许改动 --doc 指定的**一篇**文档，SQL 带 id 精确匹配，改动行数 != 1 直接 rollback；
  * 若该文档 meta 含 pageindex_tree / pageindex_status，直接拒绝（避免破坏树索引文档）；
  * 只删除 index_type 一个键，其余 meta 原样保留；
  * 打印 before/after 的 meta 键集合（不打印任何正文）。

运行：
    cd /home/harry.zhang/kb-management
    backend/.venv/bin/python 03-testing/curl/lib/strip_index_type.py \
        --doc <document_id> --expect-kb <kb_id>
首次编写：2026-10-12（PI-V3，卡 t_bbb32bcf）
"""
from __future__ import annotations

import argparse
import json
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
    ap = argparse.ArgumentParser(description="删除指定文档的 meta.index_type（模拟历史老文档）")
    ap.add_argument("--doc", required=True, help="document.id（完整 UUID）")
    ap.add_argument("--expect-kb", required=True, help="必须匹配的 kb_id（防止误改其它 KB）")
    a = ap.parse_args()

    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT d.id::text, d.kb_id::text, d.filename, d.status, d.meta
            FROM document d
            WHERE d.id::text = :id AND d.is_deleted = false
        """), {"id": a.doc}).mappings().first()
        if not row:
            sys.exit(f"[strip] 拒绝：找不到文档 {a.doc}（或已 soft-delete）")
        if row["kb_id"] != a.expect_kb:
            sys.exit(f"[strip] 拒绝：文档属于 kb={row['kb_id']}，与 --expect-kb={a.expect_kb} 不符")
        meta = dict(row["meta"] or {})
        print(f"[strip] doc={a.doc} kb={row['kb_id']} file={row['filename']} status={row['status']}")
        print(f"[strip] meta keys before = {sorted(meta.keys())}")
        if "pageindex_tree" in meta or "pageindex_status" in meta:
            sys.exit("[strip] 拒绝：该文档含 PageIndex 树相关键，不在本脚本允许范围内")
        if "index_type" not in meta:
            sys.exit("[strip] 终止：meta 里本来就没有 index_type，无需模拟")

        removed = meta.pop("index_type")
        n = db.execute(text("""
            UPDATE document SET meta = CAST(:m AS jsonb), updated_at = now()
            WHERE id::text = :id AND is_deleted = false
        """), {"m": json.dumps(meta, ensure_ascii=False), "id": a.doc}).rowcount
        if n != 1:
            db.rollback()
            sys.exit(f"[strip] 拒绝：UPDATE 影响行数={n}（期望 1），已 rollback")
        db.commit()
        print(f"[strip] removed index_type={removed!r}  受影响行数={n}")
        print(f"[strip] meta keys after  = {sorted(meta.keys())}")

        chk = db.execute(text("SELECT meta->>'index_type' FROM document WHERE id::text = :id"),
                         {"id": a.doc}).scalar()
        print(f"[strip] 复核 meta->>'index_type' = {chk!r}（应为 None）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
