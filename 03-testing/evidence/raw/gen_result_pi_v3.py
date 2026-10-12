#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_result_pi_v3.py — 汇总 VI-PI-3（卡 t_bbb32bcf，用例 4 + 用例 5）逐条断言与关键数字

输入（全部由本卡脚本产出，不引入外部结论）:
  evidence/raw/PI-04_result.json          用例4 embedding 回归（含显式 pageindex 对照）
  evidence/raw/PI-06_result.json          用例5-步骤5 存量真实文档重建索引
  evidence/raw/PI-07_result.json          用例5-步骤6 模拟无 index_type 老文档
  evidence/PI-V3_legacy_audit.json        用例5-步骤4 存量只读审计（legacy_audit.py）
  evidence/PI-V3_case4_run2.txt / PI-V3_case6_run2.txt / PI-V3_case7_run2.txt / PI-V3_case4_ke_e2e.txt

输出:
  evidence/PI-V3_result.json              逐条断言 + 关键数字 + 观察项
  evidence/PI-V3_case4_case5.txt          原始输出合集（按段落加标题）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/home/harry.zhang/kb-management")
EVID = REPO / "03-testing" / "evidence"
RAW = EVID / "raw"


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"_load_error": f"{p}: {e}"}


def main():
    r04 = load(RAW / "PI-04_result.json")
    r06 = load(RAW / "PI-06_result.json")
    r07 = load(RAW / "PI-07_result.json")
    audit = load(EVID / "PI-V3_legacy_audit.json")

    checks = []
    for case, r in (("PI-04", r04), ("PI-06", r06), ("PI-07", r07)):
        for c in r.get("checks", []):
            checks.append({"case": case, **c})
    for name, a in (audit.get("assertions") or {}).items():
        if "verdict" in a:
            if "violations" in a:
                exp, act = "violations=0", f"violations={a['violations']}"
            elif "none_total" in a:
                exp = "非本卡模拟的 <none> 文档数=0"
                act = (f"none_total={a['none_total']} 本卡模拟="
                       f"{a['none_emulated_by_pi_v3']} 其它={a['none_other']}")
            else:
                exp, act = "-", "-"
            checks.append({"case": "PI-05-AUDIT", "id": name, "desc": a["claim"],
                           "expected": exp, "actual": act, "verdict": a["verdict"]})

    fails = [c for c in checks if c["verdict"] == "FAIL"]
    not_run = [c for c in checks if c["verdict"] == "NOT-RUN"]

    # 关键数字
    key = {
        "legacy_total_docs": audit.get("totals", {}).get("all_live_docs"),
        "legacy_scope_docs": audit.get("totals", {}).get("legacy_scope_docs"),
        "pre_change_scope_docs": audit.get("totals", {}).get("pre_change_scope_docs"),
        "legacy_index_type_dist": audit.get("index_type_dist_legacy"),
        "all_index_type_dist": audit.get("index_type_dist_all"),
        "status_by_index_type_all": audit.get("status_by_index_type_all"),
        "tree_presence_by_index_type_all": audit.get("tree_presence_by_index_type_all"),
        "uploaded_at_range_all": audit.get("uploaded_at_range_all"),
        "uploaded_at_range_legacy": audit.get("uploaded_at_range_legacy"),
        "kb_grouping_summary": audit.get("kb_grouping_summary"),
        "num_docs_without_index_type": sum(
            v for k, v in (audit.get("index_type_dist_all") or {}).items() if k == "<none>"),
        "live_legacy_samples": {
            k: len(v) for k, v in (audit.get("live_kb_legacy_samples") or {}).items()},
        "case4_kb": r04.get("kb_id"), "case4_doc_embedding": r04.get("doc_embedding"),
        "case4_doc_pageindex_control": r04.get("doc_pageindex_control"),
        "case6_sample_embedding": r06.get("sample_embedding"),
        "case6_sample_pageindex": r06.get("sample_pageindex"),
        "case7_kb": r07.get("kb_id"), "case7_doc": r07.get("doc_id"),
        "case7_vue_fallback_hits": r07.get("vue_fallback_hits"),
    }

    observations = [
        {
            "id": "OBS-REINDEX-CHUNK-DUP",
            "title": "文档级重建索引(embedding 路径)不清理旧分块：PG chunk 行与 ES 文档重复堆积",
            "evidence": [
                "evidence/raw/PI-06_chunks_before.txt / PI-06_chunks_after.txt",
                "evidence/raw/PI-06_search_vector.json",
            ],
            "observed": ("同一 embedding 文档 reindex 前后：PG chunk_rows 1 → 2 → 3（本次脚本执行 2 次），"
                         "doc.chunk_count 恒为 1；KB 内 mode=vector 检索 total 同步 1 → 2 → 3，"
                         "返回 content/score 完全相同的重复条目"),
            "code": ("workers/tasks.py chunk_index_task 只 db.add 新 Chunk + es_client.index_chunks(index)，"
                     "未按 document_id 先删除 PG 旧行 / ES 旧文档；documents.py reindex 亦无清理步骤"),
            "caused_by_this_change": False,
            "note": "属改动卡 t_7f451c5f 之前的既有实现行为，不作为本卡 PASS/FAIL 依据；建议单独立卡。",
            "severity_suggestion": "P2（影响「重建索引」语义与检索结果去重）",
        },
        {
            "id": "OBS-KB-SOFTDELETED-COVERAGE",
            "title": "存量文档多数位于已软删 KB 内：行为性回归只能覆盖 live KB 子集",
            "evidence": ["evidence/PI-V3_legacy_audit.json → kb_grouping_summary"],
            "observed": (f"全量 {audit.get('totals', {}).get('all_live_docs')} 篇（is_deleted=false 文档）中 "
                         f"{audit.get('kb_grouping_summary', {}).get('docs_in_deleted_kb')} 篇所在 KB 已 is_deleted=true；"
                         f"仅 {audit.get('kb_grouping_summary', {}).get('docs_in_live_kb')} 篇在 live KB 内；"
                         f"其中符合「存量上界」且 index_type=pageindex 的 live 样本 "
                         f"{len(audit.get('live_kb_legacy_samples', {}).get('pageindex', []))} 篇、"
                         f"embedding {len(audit.get('live_kb_legacy_samples', {}).get('embedding', []))} 篇"
                         f"（含本卡行为测试后新增）"),
            "note": "只读审计覆盖全量；行为性操作（重建索引）覆盖 live 子集，报告中需明示覆盖边界。",
        },
        {
            "id": "OBS-STOCK-NO-INDEX-TYPE-ZERO",
            "title": "真实存量中不存在「无 index_type」文档 → 用例 5 步骤 6 只能做模拟",
            "evidence": ["evidence/PI-V3_legacy_audit.json → index_type_dist_all", "db_probe legacy = 0 行"],
            "observed": ("本卡执行 case_PI-07 之前的全量审计：index_type_dist_all 无 <none>（embedding 77 / pageindex 34），"
                         "db_probe legacy 探针 0 行 → 真实存量中不存在「无 index_type」文档。"
                         "本卡 PI-07 执行后新出现 2 篇 <none>，全部为本卡自建 KB（验证-兜底-legacy-VI-PI-3-*）"
                         "内人工删键的模拟文档，见 assertions.A5_no_real_legacy_docs（其它=0）。"),
            "note": "故 case_PI-07 全流程显式标注为模拟用例，不得当作存量真实分布。",
        },
    ]

    out = {
        "batch": "VI-PI-3",
        "task": "t_bbb32bcf",
        "title": "用例4（显式 embedding 上传回归）+ 用例5（存量/无 index_type 兜底不受影响）",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS" if not fails else "FAIL",
        "fails": len(fails),
        "not_run": len(not_run),
        "cases": {
            "case4": {"verdict": r04.get("verdict"), "fails": r04.get("fails")},
            "case5_step4_legacy_audit": {
                "verdict": "PASS" if all(
                    (audit.get("assertions", {}).get(k, {}).get("verdict") == "PASS")
                    for k in ("A1_legacy_embedding_no_tree", "A2_no_illegal_index_type",
                              "A3_all_scope_variants")) else "FAIL",
                "assertions": {k: v.get("verdict") for k, v in (audit.get("assertions") or {}).items()},
            },
            "case5_step5_real_reindex": {"verdict": r06.get("verdict"), "fails": r06.get("fails")},
            "case5_step6_emulated_no_index_type": {
                "verdict": r07.get("verdict"), "fails": r07.get("fails"),
                "simulated": bool(r07.get("simulated")), "note": r07.get("simulated_note")},
            "case4_ke_e2e_control": {
                "cmd": "cd backend && .venv/bin/python ../tests/e2e_test.py",
                "log": "evidence/PI-V3_case4_ke_e2e.txt",
                "verdict": "PASS（脚本自带 8 步全通过，exit 0；含 hybrid 检索 + RAG 问答 sources=1）",
                "note": "任务书建议的 pytest 形式不适用（该文件是 __main__ 脚本，pytest 收集不到用例），已改为直接执行脚本。",
            },
        },
        "key_numbers": key,
        "checks": checks,
        "failing_checks": fails,
        "observations": observations,
        "constraints_respected": {
            "code_unchanged": True,
            "services_not_restarted": True,
            "no_real_business_kb_touched": True,
            "behavioral_ops_scope": "仅历史测试 KB（live）+ 本卡自建 KB",
            "db_write_scope": "仅 1 处：strip_index_type.py 删除本卡自建文档的 meta.index_type",
            "no_subcards_created": True,
            "no_case_2_or_6": True,
        },
    }
    (EVID / "PI-V3_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gen] wrote {EVID / 'PI-V3_result.json'}  verdict={out['verdict']} checks={len(checks)} fails={len(fails)}")

    # 原始输出合集
    parts = [
        ("A. 用例4 — case_PI-04_upload_embedding.sh 首次执行原始输出（run2，run1 仅 summary 生成处有 jq 拼装笔误，判定相同）",
         EVID / "PI-V3_case4_run2.txt"),
        ("B. 用例4 — KE 回归对照 tests/e2e_test.py 原始输出",
         EVID / "PI-V3_case4_ke_e2e.txt"),
        ("C. 用例5 步骤4 — 存量只读审计 legacy_audit.py 原始输出（首次执行）",
         EVID / "PI-V3_legacy_audit_run1.txt"),
        ("D. 用例5 步骤5 — case_PI-06_reindex_legacy_embedding.sh 首次执行原始输出（run2；run1 因样本 KB 已软删 404，已换 live KH 样本）",
         EVID / "PI-V3_case6_run2.txt"),
        ("E. 用例5 步骤6 — case_PI-07_legacy_emulated_no_index_type.sh 首次执行原始输出（run2，模拟用例）",
         EVID / "PI-V3_case7_run2.txt"),
    ]
    buf = [f"{'-' * 78}\n# VI-PI-3（卡 t_bbb32bcf）原始输出合集\n"
           f"# 生成时间(UTC): {datetime.now(timezone.utc).isoformat()}\n"
           f"# 说明: 以下为各脚本/探针/测试套件的原始 stdout，未经改写；token 从未落盘。\n{'-' * 78}\n"]
    for title, p in parts:
        buf.append(f"\n\n{'=' * 78}\n## {title}\n{'=' * 78}\n")
        buf.append(p.read_text(encoding="utf-8") if p.exists() else f"(缺失: {p})\n")
    (EVID / "PI-V3_case4_case5.txt").write_text("".join(buf), encoding="utf-8")
    print(f"[gen] wrote {EVID / 'PI-V3_case4_case5.txt'}")


if __name__ == "__main__":
    main()
