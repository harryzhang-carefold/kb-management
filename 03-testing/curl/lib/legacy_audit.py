#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""legacy_audit.py — 存量文档索引元数据【只读】全量审计（VI-PI-3 / 用例 5 步骤 4）

用途：独立证明"上传默认 embedding→pageindex"改动**未污染存量数据**：
  1) 全量 is_deleted=False 文档的 index_type / status / uploaded_at 分布
  2) 存量（uploaded_at <= 2026-10-12T03:16:05Z，commit 3dc1ddf 时间）的 index_type 分布
  3) 硬断言：
     - A: 存量集合中 index_type=='embedding' 的文档**不得有任何 pageindex_tree**
     - B: 不得存在 index_type 取值非法（既非 embedding 也非 pageindex）的文档
  4) 按 KB 名分组，区分业务 KB 与历史「自测/验证」测试 KB
  5) 逐文档脱敏清单（doc_id 前 8 位、kb 名前 20 字符、index_type、status、uploaded_at）

只读保证：会话起始 SET TRANSACTION READ ONLY；全部为 SELECT；不写库、不改任何数据。
输出：默认写 03-testing/evidence/PI-V3_legacy_audit.json（--out 可覆盖），并回显人类可读摘要。

运行：
    cd /home/harry.zhang/kb-management
    backend/.venv/bin/python 03-testing/curl/lib/legacy_audit.py
首次编写：2026-10-12（PI-V3，卡 t_bbb32bcf）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parents[3]                      # .../kb-management
_BACKEND = _REPO / "backend"
if not (_BACKEND / "app" / "core" / "database.py").exists():
    sys.exit(f"[legacy_audit] 找不到 {_BACKEND}/app/core/database.py，请确认仓库路径")
sys.path.insert(0, str(_BACKEND))
os.chdir(_BACKEND)

from sqlalchemy import text                   # noqa: E402
from app.core.database import SessionLocal, engine    # noqa: E402

engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# 存量上界 = 改动卡 commit 3dc1ddf 时间；严格改动前子集按任务书口径
UPPER_BOUND = datetime(2026, 10, 12, 3, 16, 5, tzinfo=timezone.utc)
PRE_CHANGE = datetime(2026, 10, 12, 2, 40, 0, tzinfo=timezone.utc)

# 历史「自测/验证」测试 KB 名特征（用于区分业务 KB 与测试 KB）
TEST_KB_RE = re.compile(
    r"自测|验证|验收|测试|单测|selftest|verify|verify6|test|e2e|E2E|pi-|PI-|auto验收|bug0|"
    r"nginx-|stability|UI|模式错配|empty|A1-test|single-kb|sse-|deepseek-verify|"
    r"regress|bugfix|ttest|边界|edge",
    re.IGNORECASE,
)
# 说明：仅 GINA 一个 KB 名不带任何测试痕迹，按"疑似业务 KB"单列（其 3 篇文档均为 pageindex）；
#       本批**不对任何疑似业务 KB 的文档做行为性操作**，只做只读审计。


def _live_samples(docs: list) -> dict:
    """列出 KB 未删除、且可做行为性操作的存量样本（用例 5 的选用依据）"""
    live = [d for d in docs if d["in_legacy_scope"] and not d["kb_deleted"]
            and d["status"] == "indexed"]
    return {
        "pageindex": [{"doc_id": d["doc_id"], "doc_id8": d["doc_id8"], "kb_id": d["kb_id"],
                       "kb_name": d["kb_name"], "filename": d["filename"],
                       "pageindex_status": d["pageindex_status"],
                       "has_tree": d["has_pageindex_tree"]}
                      for d in live if d["index_type"] == "pageindex"],
        "embedding": [{"doc_id": d["doc_id"], "doc_id8": d["doc_id8"], "kb_id": d["kb_id"],
                       "kb_name": d["kb_name"], "filename": d["filename"],
                       "chunk_count": d["chunk_count"]}
                      for d in live if d["index_type"] == "embedding"],
    }


def audit() -> dict:
    db = SessionLocal()
    try:
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
        except Exception:
            db.rollback()

        sql = text("""
            SELECT d.id::text AS doc_id,
                   d.kb_id::text AS kb_id,
                   COALESCE(kb.name, '<no-kb>') AS kb_name,
                   COALESCE(kb.is_deleted, true) AS kb_deleted,
                   d.filename,
                   d.status,
                   d.chunk_count,
                   d.uploaded_at,
                   d.indexed_at,
                   d.meta->>'index_type' AS index_type,
                   d.meta->>'pageindex_status' AS pageindex_status,
                   (d.meta ? 'pageindex_tree') AS has_tree,
                   jsonb_typeof(d.meta->'pageindex_tree') AS tree_type,
                   d.meta AS meta_full
            FROM document d
            LEFT JOIN knowledge_base kb ON kb.id = d.kb_id
            WHERE d.is_deleted = false
            ORDER BY d.uploaded_at NULLS FIRST, d.id
        """)
        rows = [dict(r) for r in db.execute(sql).mappings().all()]
    finally:
        db.close()

    def _dt(v):
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    docs = []
    for r in rows:
        meta = r.pop("meta_full") or {}
        tree = meta.get("pageindex_tree")
        node_count = None
        if isinstance(tree, dict):
            if isinstance(tree.get("node_count"), int):
                node_count = tree["node_count"]
            else:
                def _count(n):
                    if not isinstance(n, dict):
                        return 0
                    return 1 + sum(_count(c) for c in (n.get("children") or []))
                root = tree.get("root")
                if isinstance(root, dict):
                    node_count = _count(root)
        up = _dt(r["uploaded_at"])
        it = r["index_type"]
        rec = {
            "doc_id8": r["doc_id"][:8],
            "doc_id": r["doc_id"],
            "kb_id": r["kb_id"],
            "kb_name20": (r["kb_name"] or "")[:20],
            "kb_name": r["kb_name"],
            "kb_deleted": bool(r["kb_deleted"]),
            "filename": r["filename"],
            "is_test_kb": bool(TEST_KB_RE.search(r["kb_name"] or "")),
            "index_type": it,
            "index_type_effective": it if it is not None else "<none->embedding兜底>",
            "index_type_illegal": (it not in (None, "embedding", "pageindex")),
            "status": r["status"],
            "chunk_count": r["chunk_count"],
            "pageindex_status": r["pageindex_status"],
            "has_pageindex_tree": bool(r["has_tree"]),
            "pageindex_tree_type": r["tree_type"],
            "pageindex_node_count": node_count,
            "uploaded_at": up.isoformat() if up else None,
            "indexed_at": _dt(r["indexed_at"]).isoformat() if r["indexed_at"] else None,
            "meta_keys": sorted(meta.keys()),
            "in_legacy_scope": bool(up and up <= UPPER_BOUND),
            "in_pre_change_scope": bool(up and up < PRE_CHANGE),
        }
        docs.append(rec)

    legacy = [d for d in docs if d["in_legacy_scope"]]
    prechg = [d for d in docs if d["in_pre_change_scope"]]

    def _dist(sel, key):
        return dict(sorted(Counter((d[key] if d[key] is not None else "<none>") for d in sel).items()))

    def _status_by_it(sel):
        out = defaultdict(Counter)
        for d in sel:
            out[d["index_type_effective"]][d["status"] or "<none>"] += 1
        return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}

    def _status_by_it_tree(sel):
        out = defaultdict(Counter)
        for d in sel:
            out[d["index_type_effective"]][f"tree={d['has_pageindex_tree']}"] += 1
        return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}

    ups = [d["uploaded_at"] for d in docs if d["uploaded_at"]]
    legacy_ups = [d["uploaded_at"] for d in legacy if d["uploaded_at"]]

    # 按 KB 名分组（业务 / 测试）
    by_kb = defaultdict(lambda: {"docs": 0, "pageindex": 0, "embedding": 0, "none": 0,
                                 "status": Counter(), "kb_id": None, "is_test_kb": None,
                                 "kb_deleted": None})
    for d in docs:
        g = by_kb[d["kb_name"]]
        g["docs"] += 1
        g["kb_id"] = d["kb_id"]
        g["is_test_kb"] = d["is_test_kb"]
        g["kb_deleted"] = d["kb_deleted"]
        it = d["index_type"]
        if it == "pageindex":
            g["pageindex"] += 1
        elif it == "embedding":
            g["embedding"] += 1
        else:
            g["none"] += 1
        g["status"][d["status"] or "<none>"] += 1
    by_kb_list = []
    for name, g in sorted(by_kb.items(), key=lambda kv: -kv[1]["docs"]):
        by_kb_list.append({
            "kb_id": g["kb_id"],
            "kb_name": name,
            "is_test_kb": g["is_test_kb"],
            "kb_deleted": g["kb_deleted"],
            "docs": g["docs"],
            "cnt_pageindex": g["pageindex"],
            "cnt_embedding": g["embedding"],
            "cnt_none": g["none"],
            "status_dist": dict(sorted(g["status"].items())),
        })

    # ---- 硬断言 ----
    emb_with_tree_all = [d for d in docs if d["index_type"] == "embedding" and d["has_pageindex_tree"]]
    emb_with_tree_legacy = [d for d in legacy if d["index_type"] == "embedding" and d["has_pageindex_tree"]]
    illegal_all = [d for d in docs if d["index_type_illegal"]]
    illegal_legacy = [d for d in legacy if d["index_type_illegal"]]
    pi_wo_tree = [d for d in docs if d["index_type"] == "pageindex" and d["status"] == "indexed"
                  and not d["has_pageindex_tree"]]

    # 无 index_type（<none>）文档：真实存量为 0 篇；若出现，必须逐个点名来源，
    # 避免把本卡 case_PI-07 的模拟产物当成"存量老文档"。
    EMU_RE = re.compile(r"VI-PI-3", re.IGNORECASE)
    none_docs = [d for d in docs if d["index_type"] is None]
    none_docs_detail = [{
        "doc_id": d["doc_id"], "doc_id8": d["doc_id8"], "kb_id": d["kb_id"],
        "kb_name": d["kb_name"], "filename": d["filename"], "status": d["status"],
        "chunk_count": d["chunk_count"], "uploaded_at": d["uploaded_at"],
        "likely_emulated_by_pi_v3": bool(EMU_RE.search(d["kb_name"] or "")),
    } for d in none_docs]

    emb_idx_zero_chunk = [d for d in legacy if d["index_type"] == "embedding"
                          and d["status"] == "indexed" and not (d["chunk_count"] or 0) > 0]
    emb_idx_with_chunk = [d for d in legacy if d["index_type"] == "embedding"
                          and d["status"] == "indexed" and (d["chunk_count"] or 0) > 0]

    assertions = {
        "A1_legacy_embedding_no_tree": {
            "claim": "存量集合中 index_type==embedding 的文档没有任何 pageindex_tree",
            "embedding_in_legacy": sum(1 for d in legacy if d["index_type"] == "embedding"),
            "violations": len(emb_with_tree_legacy),
            "violating_docs": [d["doc_id8"] for d in emb_with_tree_legacy],
            "verdict": "PASS" if not emb_with_tree_legacy else "FAIL",
        },
        "A2_no_illegal_index_type": {
            "claim": "不存在 index_type 取值非法（既非 embedding 也非 pageindex）的文档",
            "checked_total": len(docs),
            "violations": len(illegal_all),
            "violating_docs": [{"doc_id8": d["doc_id8"], "kb": d["kb_name20"],
                                "index_type": d["index_type"]} for d in illegal_all],
            "verdict": "PASS" if not illegal_all else "FAIL",
        },
        "A3_all_scope_variants": {
            "claim": "同一断言在（全量 / 存量上界内 / 严格改动前子集）三个口径下均成立",
            "full_scope_embedding_with_tree": len(emb_with_tree_all),
            "legacy_scope_embedding_with_tree": len(emb_with_tree_legacy),
            "pre_change_scope_illegal": len(illegal_legacy),
            "verdict": "PASS" if (not emb_with_tree_all and not emb_with_tree_legacy
                                  and not illegal_legacy) else "FAIL",
        },
        "A4_legacy_embedding_still_chunked": {
            "claim": "存量 index_type==embedding 且 status==indexed 的文档仍保有分块（chunk_count>0）",
            "checked": len(emb_idx_with_chunk) + len(emb_idx_zero_chunk),
            "with_chunks": len(emb_idx_with_chunk),
            "violations": len(emb_idx_zero_chunk),
            "violating_docs": [{"doc_id8": d["doc_id8"], "kb": d["kb_name20"]}
                               for d in emb_idx_zero_chunk],
            "verdict": "PASS" if not emb_idx_zero_chunk else "WARN",
        },
        "A5_no_real_legacy_docs": {
            "claim": ("真实存量中不存在「无 index_type」文档（<none> 只允许是本卡 PI-07 模拟产物）"),
            "none_total": len(none_docs),
            "none_emulated_by_pi_v3": sum(1 for d in none_docs_detail if d["likely_emulated_by_pi_v3"]),
            "none_other": sum(1 for d in none_docs_detail if not d["likely_emulated_by_pi_v3"]),
            "docs": none_docs_detail,
            "verdict": "PASS" if not any(not d["likely_emulated_by_pi_v3"] for d in none_docs_detail)
                       else "FAIL",
        },
        "OBS1_pageindex_indexed_without_tree": {
            "claim": "观察项（不判 FAIL）：index_type==pageindex 且 status==indexed 但无 tree 的文档数",
            "count": len(pi_wo_tree),
            "docs": [{"doc_id8": d["doc_id8"], "kb": d["kb_name20"],
                      "pageindex_status": d["pageindex_status"]} for d in pi_wo_tree[:20]],
        },
    }

    return {
        "probe": "legacy_audit.py (read-only)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scopes": {
            "legacy_upper_bound": UPPER_BOUND.isoformat(),
            "pre_change_subset": f"uploaded_at < {PRE_CHANGE.isoformat()}",
        },
        "totals": {
            "all_live_docs": len(docs),
            "legacy_scope_docs": len(legacy),
            "pre_change_scope_docs": len(prechg),
        },
        "index_type_dist_all": _dist(docs, "index_type"),
        "index_type_dist_legacy": _dist(legacy, "index_type"),
        "index_type_dist_pre_change": _dist(prechg, "index_type"),
        "status_by_index_type_all": _status_by_it(docs),
        "status_by_index_type_legacy": _status_by_it(legacy),
        "tree_presence_by_index_type_all": _status_by_it_tree(docs),
        "uploaded_at_range_all": {"min": min(ups) if ups else None, "max": max(ups) if ups else None},
        "uploaded_at_range_legacy": {"min": min(legacy_ups) if legacy_ups else None,
                                     "max": max(legacy_ups) if legacy_ups else None},
        "by_kb": by_kb_list,
        "kb_grouping_summary": {
            "business_kb_count": sum(1 for k in by_kb_list if not k["is_test_kb"]),
            "test_kb_count": sum(1 for k in by_kb_list if k["is_test_kb"]),
            "business_docs": sum(k["docs"] for k in by_kb_list if not k["is_test_kb"]),
            "test_docs": sum(k["docs"] for k in by_kb_list if k["is_test_kb"]),
            "docs_in_deleted_kb": sum(k["docs"] for k in by_kb_list if k["kb_deleted"]),
            "docs_in_live_kb": sum(k["docs"] for k in by_kb_list if not k["kb_deleted"]),
            "note": "kb_deleted=true 的文档只能做只读审计；用例 5 的行为性操作(重建索引)只允许落在 live KB",
        },
        "live_kb_legacy_samples": _live_samples(docs),
        "assertions": assertions,
        "docs": docs,     # 逐文档脱敏清单（无正文、无 full_text、无 token）
    }


def main():
    ap = argparse.ArgumentParser(description="存量文档索引元数据只读全量审计")
    ap.add_argument("--out", default=str(_REPO / "03-testing" / "evidence" / "PI-V3_legacy_audit.json"))
    a = ap.parse_args()

    data = audit()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 逐文档脱敏清单（TSV，便于人眼核对；仍不含正文/token/密钥）
    tsv = Path(a.out).with_name("PI-V3_legacy_docs.tsv")
    lines = ["doc_id8\tkb_name20\tindex_type\tstatus\tuploaded_at\tchunk_count\t"
             "pageindex_status\thas_tree\tin_legacy_scope\tis_test_kb"]
    for d in data["docs"]:
        lines.append("\t".join([
            d["doc_id8"], d["kb_name20"], str(d["index_type"]), str(d["status"]),
            str(d["uploaded_at"]), str(d["chunk_count"]), str(d["pageindex_status"]),
            str(d["has_pageindex_tree"]), str(d["in_legacy_scope"]), str(d["is_test_kb"]),
        ]))
    tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[legacy_audit] wrote {tsv}")

    t = data["totals"]
    print(f"[legacy_audit] wrote {a.out}")
    print(f"[totals] all_live_docs={t['all_live_docs']} legacy_scope={t['legacy_scope_docs']} "
          f"pre_change_scope={t['pre_change_scope_docs']}")
    print(f"[index_type all] {data['index_type_dist_all']}")
    print(f"[index_type legacy] {data['index_type_dist_legacy']}")
    print(f"[status_by_index_type all] {data['status_by_index_type_all']}")
    print(f"[status_by_index_type legacy] {data['status_by_index_type_legacy']}")
    print(f"[tree_presence all] {data['tree_presence_by_index_type_all']}")
    print(f"[uploaded_at all] {data['uploaded_at_range_all']}")
    print(f"[uploaded_at legacy] {data['uploaded_at_range_legacy']}")
    print(f"[kb grouping] {data['kb_grouping_summary']}")
    for k, v in data["assertions"].items():
        extra = ""
        if "violations" in v:
            extra += f" violations={v['violations']}"
        if "none_total" in v:
            extra += (f" none_total={v['none_total']} emulated_by_pi_v3={v['none_emulated_by_pi_v3']}"
                      f" other={v['none_other']}")
        print(f"[ASSERT {k}] {v.get('verdict', '-')} {v['claim']}{extra}")


if __name__ == "__main__":
    main()
