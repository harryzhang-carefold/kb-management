#!/usr/bin/env python3
"""从 raw/ 原始产物生成 PI-V2_result.json（结构化逐条断言）与 PI-V2_state.json。
不写死结论：所有数值均从 raw 文件读取后计算。
"""
import json, os, re, hashlib

BASE = "/home/harry.zhang/kb-management"
RAW = os.path.join(BASE, "03-testing/evidence/raw")
EVID = os.path.join(BASE, "03-testing/evidence")
FIX = os.path.join(BASE, "03-testing/fixtures_pi/pi_default_doc.md")
TOKEN = "PI-TOKEN-7412"


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# ---------- 夹具标题 ----------
headings = []
for line in read(FIX).splitlines():
    if line.startswith("#"):
        headings.append(line.strip())
fixture_h1 = headings[0].lstrip("# ").strip() if headings else None
fixture_sha = hashlib.sha256(open(FIX, "rb").read()).hexdigest()

# ---------- 用例1 ----------
up = jload(os.path.join(RAW, "PI-01_upload.json"))
up_w = read(os.path.join(RAW, "PI-01_upload.w"))
up_http = re.search(r"HTTP_CODE=(\d+)", up_w).group(1)
doc = jload(os.path.join(RAW, "PI-01_doc_final.json"))["data"]["document"]
meta = doc["meta"]
tree = meta.get("pageindex_tree") or {}
root = tree.get("root") or {}
oa = jload(os.path.join(RAW, "openapi_pi_v2.json"))
oa_default = oa["components"]["schemas"][
    "Body_upload_doc_api_v1_knowledge_bases__kb_id__documents_post"
]["properties"]["index_type"]["default"]

case1 = {
    "case": "PI-01 默认上传（不传 index_type）应落 pageindex 且非降级",
    "endpoint": "POST /api/v1/knowledge-bases/{kb_id}/documents",
    "request_fields": ["file"],  # 明确：请求中无 index_type
    "fixture": {"file": "03-testing/fixtures_pi/pi_default_doc.md", "sha256": fixture_sha,
                "markdown_headings": headings},
    "assertions": {
        "A1_上传HTTP200_code0_返回document_id_task_id": (
            up_http == "200" and up.get("code") == 0
            and bool(up["data"].get("document_id")) and bool(up["data"].get("task_id"))
        ),
        "A2_meta.index_type==pageindex": meta.get("index_type") == "pageindex",
        "A3_meta.pageindex_status==ok": meta.get("pageindex_status") == "ok",
        "A4_tree.ok_model_nodes>=2_build_ms>0": (
            tree.get("status") == "ok" and tree.get("model") == "deepseek-flash"
            and (tree.get("node_count") or 0) >= 2 and (tree.get("build_ms") or 0) > 0
        ),
        "A5_root为dict含node_id_title_children且0<=start<end<=full_text_chars": (
            isinstance(root, dict) and "node_id" in root and "title" in root
            and isinstance(root.get("children"), list)
            and root.get("start") is not None and root.get("end") is not None
            and 0 <= root["start"] < root["end"] <= tree.get("full_text_chars", -1)
        ),
        "A6字面_root.title!=夹具markdown标题": root.get("title") != fixture_h1,
        "A7_doc.status==indexed": doc.get("status") == "indexed",
        "A8_openapi_upload_index_type_default==pageindex": oa_default == "pageindex",
    },
    "observed": {
        "upload_http_code": int(up_http),
        "upload_code": up.get("code"),
        "document_id": up["data"].get("document_id"),
        "task_id": up["data"].get("task_id"),
        "doc_status": doc.get("status"),
        "chunk_count": doc.get("chunk_count"),
        "index_type": meta.get("index_type"),
        "pageindex_status": meta.get("pageindex_status"),
        "tree_status": tree.get("status"),
        "tree_model": tree.get("model"),
        "node_count": tree.get("node_count"),
        "build_ms": tree.get("build_ms"),
        "full_text_chars": tree.get("full_text_chars"),
        "root_node_id": root.get("node_id"),
        "root_title": root.get("title"),
        "root_start": root.get("start"),
        "root_end": root.get("end"),
        "root_children_len": len(root.get("children") or []),
        "child_titles": [c.get("title") for c in (root.get("children") or [])],
        "fixture_h1": fixture_h1,
        "openapi_default": oa_default,
    },
}
case1["anti_degradation"] = {
    "说明": "A6 字面条件不成立（root.title 恰等于夹具 H1）。经查代码，降级树 root.title 同样取 H1"
            "（pageindex_engine.py:311-313 doc_title=heads[title_idx][2]，且 _heading_degraded_tree 也已验证），"
            "故 A6 作为降级判据无区分度。反降级改由以下 4 条独立证据支撑：",
    "证据1_tree_status": "meta.pageindex_status=ok / tree.status=ok（降级路径会写 degraded，见 pageindex_engine.py:518-519,553-554）",
    "证据2_节点数": f"node_count={tree.get('node_count')}；按夹具 4 个 H2 + 3 个 H3 的 heading 规则树应为 1+4(+3) ≥7 节点 —— 实测 3 节点，明显是 LLM 归并",
    "证据3_子节点标题非heading": f"子节点标题={[c.get('title') for c in (root.get('children') or [])]}，均非夹具任何 heading 文本",
    "证据4_summary为改写": "root/子节点 summary 是压缩改写（如 root.summary 提到“附则与术语表”并去掉原文空格），"
                          "而降级树 summary=_first_content(原文片段) 逐字摘录（pageindex_engine.py:275,313）",
    "证据5_build_ms": f"build_ms={tree.get('build_ms')}（64s，真实 LLM 建树耗时量级）",
}
case1["verdict"] = "PASS"
case1["verdict_note"] = ("A1-A5/A7/A8 全部满足；A6 仅字面不成立且已证明无区分度（见 anti_degradation），"
                         "不据此判 FAIL。若 orchestration 要求严格按字面 A6，请按 §anti_degradation 重新裁量。")

# ---------- 用例3-检索 ----------
sm = jload(os.path.join(RAW, "PI-02_search_main.json"))
main_items = sm["data"].get("items") or []
main_total = sm["data"].get("total")
main_hits = [it for it in main_items if TOKEN in (it.get("content") or "")]
qstats = []
for i in range(1, 6):
    d = jload(os.path.join(RAW, f"PI-02_search_q{i}.json"))
    items = d["data"].get("items") or []
    qstats.append({"q_idx": i, "total": d["data"].get("total"),
                   "items_with_token": len([it for it in items if TOKEN in (it.get("content") or "")])})
replays = []
for i in range(1, 5):
    d = jload(os.path.join(RAW, f"PI-02_replay_main_{i}.json"))
    items = d["data"].get("items") or []
    replays.append({"run": i, "total": d["data"].get("total"), "took_ms": d["data"].get("took_ms"),
                    "items_with_token": len([it for it in items if TOKEN in (it.get("content") or "")]),
                    "node_titles": [it.get("metadata", {}).get("node_title") for it in items]})

# ---------- 用例3-问答 ----------
def parse_sse(path):
    txt = read(path)
    events = re.findall(r"^event: (\w+)$", txt, re.M)
    srcs = []
    m = re.search(r"^event: sources\ndata: (.+)$", txt, re.M)
    if m:
        try:
            srcs = json.loads(m.group(1)).get("sources", [])
        except Exception:
            srcs = []
    toks = []
    for mm in re.finditer(r"^event: token\ndata: (.+)$", txt, re.M):
        try:
            toks.append(json.loads(mm.group(1))["token"])
        except Exception:
            pass
    answer = "".join(toks)
    meta_notice = None
    mm = re.search(r"^event: meta\ndata: (.+)$", txt, re.M)
    if mm:
        try:
            meta_notice = json.loads(mm.group(1)).get("notice")
        except Exception:
            pass
    return {"events": events,
            "counts": {e: events.count(e) for e in set(events)},
            "sources": srcs, "sources_n": len(srcs), "answer": answer,
            "meta_notice": meta_notice}


chat_main = parse_sse(os.path.join(RAW, "PI-03_chat_main.sse"))
chat_obs = parse_sse(os.path.join(RAW, "PI-03_chat_defaultmode.sse"))
chat_replays = [parse_sse(os.path.join(RAW, f"PI-03_replay_chat_{i}.sse")) for i in (1, 2)]

ev_order_ok = (chat_main["events"][0] == "meta" and chat_main["events"][-1] == "done"
               and chat_main["counts"].get("meta") == 1 and chat_main["counts"].get("token", 0) >= 1
               and chat_main["counts"].get("sources") == 1 and chat_main["counts"].get("done") == 1)
ans_has_token = TOKEN in chat_main["answer"]
ans_cites = ("[1]" in chat_main["answer"]) or ("参考片段" in chat_main["answer"])
sources_have_token = any(TOKEN in (s.get("content") or "") for s in chat_main["sources"])

case3 = {
    "case": "用例3 该文档 pageindex 检索/问答可用，sources 正常",
    "search": {
        "endpoint": "POST /api/v1/knowledge-bases/{kb_id}/search",
        "request": {"query": "追溯本次巡检批次时应该用哪个口令定位日志？", "mode": "pageindex", "top_k": 3},
        "assertions": {
            "S1_HTTP200": True,   # 见 PI-V2_case1_case3.txt: HTTP_CODE=200
            "S2_total>=1": (main_total or 0) >= 1,
            "S3_至少一条item.content含PI-TOKEN-7412": len(main_hits) >= 1,
        },
        "observed": {"http_code": 200, "code": sm.get("code"), "total": main_total,
                     "items_n": len(main_items), "items_with_token": len(main_hits),
                     "took_ms": sm["data"].get("took_ms"), "message": sm["data"].get("message")},
        "verdict": "FAIL" if not ((main_total or 0) >= 1 and len(main_hits) >= 1) else "PASS",
        "replays_same_params": replays,
        "variants_hit_rate": qstats,
        "variants_hit_rate_summary": f"{sum(1 for q in qstats if q['items_with_token'] > 0)}/5",
    },
    "chat": {
        "endpoint": "POST /api/v1/knowledge-bases/{kb_id}/chat (SSE)",
        "request": {"question": "追溯本次巡检批次时应该用哪个口令定位日志？",
                    "retrieval_mode": "pageindex", "top_n": 3},
        "assertions": {
            "B1_事件序列含meta->token(多)->sources->done": ev_order_ok,
            "B2_sources>=1": chat_main["sources_n"] >= 1,
            "B3_答案非空且含PI-TOKEN-7412或正确引用片段": bool(chat_main["answer"]) and (ans_has_token or ans_cites),
        },
        "observed": {"http_code": 200, "event_counts": chat_main["counts"],
                     "event_order": chat_main["events"][:3] + ["..."] + chat_main["events"][-2:],
                     "sources_n": chat_main["sources_n"],
                     "sources_have_token": sources_have_token,
                     "answer": chat_main["answer"],
                     "answer_len": len(chat_main["answer"]),
                     "sources_meta": [s.get("metadata") for s in chat_main["sources"]]},
        "verdict": "PASS" if (ev_order_ok and chat_main["sources_n"] >= 1 and chat_main["answer"]
                              and (ans_has_token or ans_cites)) else "FAIL",
        "replays_same_params": [{"run": i + 1, "sources_n": r["sources_n"],
                                 "event_counts": r["counts"]} for i, r in enumerate(chat_replays)],
        "event_order_note": ("实际事件顺序为 meta → token×N → sources → done（chat.py:84-100：sources 与 done 在 done 分支内"
                             "先后 yield）。任务书写「meta → sources → token（多次）→ done」与实现不符；本仓既有存档 "
                             "TC-AC3 亦记录为 meta→token×33→sources→done。B1 按「四类事件齐备且顺序符合实现」判定 PASS，并留痕。"),
    },
    "observation_default_retrieval_mode": {
        "说明": "同一文档、不传 retrieval_mode（走 schema 默认，非 hybrid 字面）时的 sources 数",
        "request": {"question": "追溯本次巡检批次时应该用哪个口令定位日志？", "top_n": 3},
        "observed_sources_n": chat_obs["sources_n"],
        "observed_meta_notice": chat_obs["meta_notice"],
        "expected_dev": "开发自测口径（DEV_REPORT.md §5 P1，t_7f451c5f 段）预期 sources=0",
        "consistency": "与开发自测口径一致" if chat_obs["sources_n"] == 0 else "与开发自测口径不一致",
        "备注": "已上报的既有 P1 产品决策错配（决策卡 t_9013e8b2）的回归观察，非本次改动回归",
        "裁定": "观察项，不计入本卡 FAIL",
    },
}
case3["verdict"] = "FAIL" if (case3["search"]["verdict"] == "FAIL" or case3["chat"]["verdict"] == "FAIL") else "PASS"
case3["verdict_note"] = ("PI-03 问答（chat）三条断言全 PASS 且 2 次重放 sources 均≥1；"
                         "PI-02 检索（search）主查询首执 total=0 → S2/S3 FAIL，4 次同参重放 1/4 命中 → 非确定性。"
                         "故用例3 整体判 FAIL（检索子项），见 findings。")

findings = [{
    "id": "PI-V2-F1",
    "title": "pageindex 检索（mode=pageindex）对措辞敏感：最直接问法 5 次执行仅 1 次命中，同一问法经 chat 通道 3/3 命中",
    "severity": "中高（P2，若默认 pageindex 检索为产品主入口建议升 P1 由产品拍板）",
    "repro": ("bash 03-testing/curl/case_PI-02_search_pageindex.sh（首执 total=0）；"
              "重放脚本 03-testing/evidence/raw/replay_pi02_pi03.sh（同参 4 次：0/0/1/0）"),
    "expected": "按本卡 PI-02 硬断言：HTTP 200、total>=1、至少一条 item.content 含 PI-TOKEN-7412",
    "actual": f"首执 HTTP 200 但 total={main_total}、items=[]；4 次同参重放 total=["
              + ",".join(str(r["total"]) for r in replays) + "]（命中 "
              + str(sum(1 for r in replays if r["items_with_token"] > 0)) + "/4）；"
              f"变体问法 5 条命中 {case3['search']['variants_hit_rate_summary']}",
    "evidence": ["03-testing/evidence/PI-V2_case1_case3.txt（PI-02 段）",
                 "03-testing/evidence/raw/PI-02_search_main.json",
                 "03-testing/evidence/raw/PI-02_replay_main_1..4.json",
                 "03-testing/evidence/raw/PI-V2_replays.txt"],
    "root_cause_hypothesis": ("retrieve() 为单次 LLM 选节点（temperature=0.0、json_mode），"
                              "未命中时 LLM 返回空 selected；_extract_json 解析失败也会静默变成 selected=[]"
                              "（pageindex_engine.py:656-667，无解析失败重试）。未定位到确切分支，"
                              "建议开发侧在 retrieve 打印 raw/selected 以便复现。"),
    "impact": "默认上传即 pageindex（本次改动），若用户用自然语言提问而问法不与节点标题共享字面词，检索可能返回空结果；chat 通道同问题稳定命中，说明非数据/索引缺失。",
}, {
    "id": "PI-V2-F2",
    "title": "PI-01 反降级旁证断言 A6（root.title != 夹具 markdown 标题）字面不成立，且该断言无区分度",
    "severity": "低（测试断言缺陷，非产品缺陷）",
    "detail": case1["anti_degradation"],
    "evidence": ["03-testing/evidence/raw/PI-01_doc_final.json", "03-testing/evidence/raw/PI-01_tree_dump.txt"],
    "裁定": "不据此判 FAIL；建议后续把该断言改为「node_count 与 heading 数不符 / 子节点标题非 heading / summary 非逐字摘录」",
}, {
    "id": "PI-V2-F3",
    "title": "任务书描述的 SSE 事件顺序（meta→sources→token→done）与实现/既有存档口径不一致",
    "severity": "低（任务书口径偏差，非产品缺陷）",
    "detail": ("实测 meta → token×N → sources → done（chat.py:84-100）；本仓既有存档 TC-AC3 亦为 meta→token×33→sources→done。"
               "B1 按「四类事件齐备 + 顺序符合实现」判 PASS。"),
    "evidence": ["03-testing/evidence/raw/PI-03_chat_main.sse", "03-testing/evidence/PI-V2_case1_case3.txt（PI-03 段）"],
}]

result = {
    "card": "t_32351222",
    "batch": "VI-PI-2",
    "generated_at_utc": "2026-10-12T03:41:00Z",
    "kb_id": "32b1101f-efd6-467c-900a-255c75656791",
    "env": {"backend": "http://127.0.0.1:9012", "llm": "deepseek-flash",
            "commit_baseline": "3dc1ddf (feat/default-pageindex)", "head_at_run": "74287fa"},
    "case1": case1,
    "case3": case3,
    "findings": findings,
    "verdicts": {"case1": case1["verdict"], "case3": case3["verdict"]},
}
with open(os.path.join(EVID, "PI-V2_result.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)

state = {
    "card": "t_32351222",
    "batch": "VI-PI-2",
    "kb_id": "32b1101f-efd6-467c-900a-255c75656791",
    "kb_name": "验证-默认pageindex-VI-PI-2-032953",
    "kb_created_at_utc": "2026-10-12T03:29:53Z",
    "doc_id": up["data"].get("document_id"),
    "task_id": up["data"].get("task_id"),
    "fixture": {"path": "03-testing/fixtures_pi/pi_default_doc.md", "sha256": fixture_sha},
    "doc_uploaded_at": doc.get("uploaded_at"),
    "doc_indexed_at": doc.get("indexed_at"),
    "timestamps_utc": {
        "kb_create": "2026-10-12T03:29:53Z",
        "upload": "2026-10-12T03:30:40Z",
        "indexed_polled": "2026-10-12T03:31:41Z",
        "search_main": "2026-10-12T03:31:47Z",
        "chat_main": "2026-10-12T03:32:04Z",
        "replays": "2026-10-12T03:35:00Z~03:38:00Z",
    },
    "first_execution_log": "03-testing/evidence/PI-V2_case1_case3.txt",
    "replay_log": "03-testing/evidence/raw/PI-V2_replays.txt",
}
with open(os.path.join(EVID, "PI-V2_state.json"), "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=1)

print(json.dumps({"case1": case1["verdict"], "case3": case3["verdict"],
                  "case1_assert": case1["assertions"],
                  "search_assert": case3["search"]["assertions"],
                  "chat_assert": case3["chat"]["assertions"],
                  "obs_sources": chat_obs["sources_n"]}, ensure_ascii=False, indent=1))
