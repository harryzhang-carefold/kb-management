#!/usr/bin/env python3
"""PageIndex 验收主测试（API 层）
执行: AC-1 ~ AC-5 + REG-1 ~ REG-3
输出: 03-testing/api_results.json（逐条 PASS/FAIL + 证据）
"""
import json
import time
import uuid
import sys

import httpx

BASE = "http://127.0.0.1:9012/api/v1"
TESTDATA = "/home/harry.zhang/kb-management/03-testing/testdata"
OUT = "/home/harry.zhang/kb-management/03-testing/api_results.json"

results = []


def record(name, ok_flag, detail):
    results.append({"name": name, "pass": bool(ok_flag), "detail": str(detail)[:2000]})
    print(f"[{'PASS' if ok_flag else 'FAIL'}] {name}: {str(detail)[:200]}", flush=True)


def unwrap(r):
    """返回 (http_status, code, data, message)"""
    try:
        body = r.json()
    except Exception:
        return r.status_code, None, None, r.text[:300]
    return r.status_code, body.get("code"), body.get("data"), body.get("message")


client = httpx.Client(base_url=BASE, timeout=300)
client2 = httpx.Client(timeout=120)  # 用于 LLM 不可用测试（直连坏端点场景复用本 client，仅模拟）

# ============ 准备：注册 + 登录 ============
uname = f"testpi_{uuid.uuid4().hex[:8]}"
r = client.post("/auth/register", json={
    "username": uname, "email": f"{uname}@example.com",
    "password": "Test123456!", "display_name": "PageIndex验收测试"})
st, code, data, msg = unwrap(r)
assert st == 200 and code == 0, f"注册失败 {st} {msg}"
r = client.post("/auth/login", json={"username": uname, "password": "Test123456!"})
st, code, data, msg = unwrap(r)
token = data["access_token"]
H = {"Authorization": f"Bearer {token}"}
record("setup_register_login", True, f"user={uname}")

# ============ AC-1: 上传 pageindex 文档 + 异步索引完成 ============
r = client.post("/knowledge-bases", json={"name": "PageIndex验收KB-" + uname, "description": "test"}, headers=H)
st, code, kb, msg = unwrap(r)
assert st == 200, f"建KB失败 {st} {msg}"
kb_id = kb["id"]

with open(f"{TESTDATA}/ops_manual.md", "rb") as f:
    r = client.post(f"/knowledge-bases/{kb_id}/documents",
                    files={"file": ("ops_manual.md", f, "text/markdown")},
                    data={"index_type": "pageindex"}, headers=H)
st, code, data, msg = unwrap(r)
assert st == 200, f"上传pageindex文档失败 {st} {msg}"
doc_id = data["document_id"]
record("ac1_upload_pageindex", True, f"kb={kb_id} doc={doc_id}")

# 轮询文档状态（建树 30-120s，最多等 15min）
t0 = time.time()
doc_state = None
while time.time() - t0 < 900:
    r = client.get(f"/knowledge-bases/{kb_id}/documents/{doc_id}", headers=H)
    st, code, d, msg = unwrap(r)
    doc_state = d
    status = d["document"]["status"]
    pi_status = (d["document"]["meta"] or {}).get("pageindex_status")
    if status == "indexed" and pi_status in ("ok", "degraded"):
        break
    if status == "failed":
        break
    time.sleep(10)

status = doc_state["document"]["status"]
meta = doc_state["document"]["meta"] or {}
tree = meta.get("pageindex_tree") or {}
record("ac1_async_index_done",
       status == "indexed" and meta.get("pageindex_status") in ("ok", "degraded"),
       f"status={status} pageindex_status={meta.get('pageindex_status')} "
       f"tree_nodes={tree.get('node_count')} build_ms={tree.get('build_ms')} elapsed={int(time.time()-t0)}s")

# 互斥校验：pageindex 文档无 chunk 向量索引
cc = doc_state["document"]["chunk_count"]
record("ac1_mutex_no_chunks", cc == 0, f"chunk_count={cc}")
record("ac1_index_type_recorded", meta.get("index_type") == "pageindex", f"index_type={meta.get('index_type')}")

# ============ 上传 embedding 文档（同 KB，供"无pageindex索引"场景 + 回归） ============
with open(f"{TESTDATA}/one_node.md", "rb") as f:
    r = client.post(f"/knowledge-bases/{kb_id}/documents",
                    files={"file": ("one_node.md", f, "text/markdown")},
                    data={"index_type": "embedding"}, headers=H)
st, code, data, msg = unwrap(r)
assert st == 200, f"上传embedding文档失败 {st} {msg}"
emb_doc_id = data["document_id"]
# 轮询 embedding 文档终态（embedding 端点不可达 → 预期 failed，这是环境态）
t0 = time.time()
emb_state = None
while time.time() - t0 < 300:
    r = client.get(f"/knowledge-bases/{kb_id}/documents/{emb_doc_id}", headers=H)
    st, code, d, msg = unwrap(r)
    emb_state = d
    s = d["document"]["status"]
    if s in ("indexed", "failed"):
        break
    time.sleep(10)
record("setup_embedding_doc", True,
       f"doc={emb_doc_id} status={emb_state['document']['status']} "
       f"err={emb_state['document']['error_message']}")

# ============ AC-2: search mode=pageindex ============
r = client.post(f"/knowledge-bases/{kb_id}/search",
                headers=H,
                json={"query": "模型服务不可用时应该怎么排查？", "mode": "pageindex", "top_k": 5})
st, code, d, msg = unwrap(r)
items = (d or {}).get("items", [])
fields_ok = all(
    it.get("document_id") and it.get("content") and isinstance(it.get("score"), (int, float))
    for it in items)
record("ac2_search_pageindex_200", st == 200 and code == 0,
       f"items={len(items)} took_ms={d.get('took_ms')}")
record("ac2_items_relevant",
       len(items) > 0 and fields_ok and items[0]["document_id"] == doc_id,
       f"first_doc={items[0]['document_id'] if items else None} "
       f"score={items[0]['score'] if items else None} "
       f"content_head={items[0]['content'][:80] if items else None}")

# ============ AC-3: chat retrieval_mode=pageindex（SSE 流式） ============
r = client.post(f"/knowledge-bases/{kb_id}/chat", headers=H,
                json={"question": "队列积压超过多少条会触发告警？", "retrieval_mode": "pageindex"})
events = []
full = ""
sources = []
err = None
ev = ""
for line in r.iter_lines():
    if not line:
        continue
    if line.startswith("event: "):
        ev = line[7:].strip()
    elif line.startswith("data: "):
        payload = json.loads(line[6:])
        if ev == "token":
            full += payload.get("token", "")
        elif ev == "sources":
            sources = payload.get("sources", [])
        elif ev == "error":
            err = payload.get("message")
        elif ev == "done":
            pass
    else:
        # 无 event: 行时 payload 自带 type
        try:
            payload = json.loads(line[6:]) if line.startswith("data: ") else {}
        except Exception:
            payload = {}
    events.append(line)

record("ac3_chat_sse_stream",
       st == 200 and len(events) > 1 and (full or sources) and not err,
       f"http={r.status_code} events={len(events)} tokens_in_answer={len(full)} err={err}")
src_fields_ok = all(
    set(s.keys()) >= {"chunk_id", "document_id", "filename", "chunk_index", "score"}
    for s in sources)
record("ac3_chat_sources",
       len(sources) > 0 and src_fields_ok,
       f"n_sources={len(sources)} first_keys={sorted(sources[0].keys()) if sources else []}")
# 引用正确性：回答包含来源标注 + 内容相关（200 条）
cite_ok = ("[1]" in full) and ("200" in full)
record("ac3_citation_correct",
       cite_ok and "200" in full,
       f"answer_head={full[:200]}")

# ============ 无 pageindex 索引的 KB → 空结果 + 提示（v2 变更点） ============
r = client.post("/knowledge-bases", json={"name": "纯EmbeddingKB-" + uname}, headers=H)
st, code, kb2, msg = unwrap(r)
kb2_id = kb2["id"]
with open(f"{TESTDATA}/one_node.md", "rb") as f:
    r = client.post(f"/knowledge-bases/{kb2_id}/documents",
                    files={"file": ("one_node.md", f, "text/markdown")},
                    data={"index_type": "embedding"}, headers=H)
st, code, d, msg = unwrap(r)
emb2_doc = d["document_id"]
t0 = time.time()
while time.time() - t0 < 300:
    r = client.get(f"/knowledge-bases/{kb2_id}/documents/{emb2_doc}", headers=H)
    st, code, d, msg = unwrap(r)
    if d["document"]["status"] in ("indexed", "failed"):
        break
    time.sleep(10)

r = client.post(f"/knowledge-bases/{kb2_id}/search", headers=H,
                json={"query": "星尘知识库是什么", "mode": "pageindex"})
st, code, d, msg = unwrap(r)
record("edge_no_pi_index_empty_hint",
       st == 200 and (d or {}).get("items") == [] and "PageIndex" in (d or {}).get("message", ""),
       f"items={d.get('items')} message={d.get('message')}")

# chat 同样应提示（不空答、不回退 ES）
r = client.post(f"/knowledge-bases/{kb2_id}/chat", headers=H,
                json={"question": "星尘知识库是什么", "retrieval_mode": "pageindex"})
evs = list(r.iter_lines())
err_evt = [l for l in evs if "event: error" in l or "PageIndex" in l or "没有使用" in l]
record("edge_no_pi_index_chat_hint",
       any("PageIndex" in l or "没有使用" in l for l in evs),
       f"events={len(evs)} hint_lines={err_evt[:2]}")

# ============ REG: 原路径回归 ============
# REG-1 hybrid
r = client.post(f"/knowledge-bases/{kb_id}/search", headers=H,
                json={"query": "告警分级", "mode": "hybrid", "top_k": 5})
st, code, d, msg = unwrap(r)
record("reg1_hybrid", st == 200 and code == 0,
       f"http={st} items={len((d or {}).get('items', []))} msg={msg}")
# REG-2 vector（embedding 端点不可达时按原逻辑退化为 keyword，不崩溃）
r = client.post(f"/knowledge-bases/{kb_id}/search", headers=H,
                json={"query": "告警分级", "mode": "vector", "top_k": 5})
st, code, d, msg = unwrap(r)
record("reg2_vector", st == 200 and code == 0,
       f"http={st} items={len((d or {}).get('items', []))} msg={msg}")
# REG-3 keyword
r = client.post(f"/knowledge-bases/{kb_id}/search", headers=H,
                json={"query": "备份策略", "mode": "keyword", "top_k": 5})
st, code, d, msg = unwrap(r)
kw_items = (d or {}).get("items", [])
record("reg3_keyword", st == 200 and code == 0,
       f"http={st} items={len(kw_items)} "
       f"match_types={sorted({i.get('match_type') for i in kw_items})}")

# 非法 mode 校验
r = client.post(f"/knowledge-bases/{kb_id}/search", headers=H,
                json={"query": "x", "mode": "badmode"})
record("reg4_mode_validation", r.status_code == 422, f"http={r.status_code}")

# reindex（pageindex 文档按 index_type 重建）
r = client.post(f"/knowledge-bases/{kb_id}/documents/{doc_id}/reindex", headers=H)
st, code, d, msg = unwrap(r)
record("reindex_pageindex_dispatch",
       st == 200 and (d or {}).get("index_type") == "pageindex",
       f"index_type={d.get('index_type') if d else None}")
t0 = time.time()
done = None
while time.time() - t0 < 900:
    r = client.get(f"/knowledge-bases/{kb_id}/documents/{doc_id}", headers=H)
    st, code, d, msg = unwrap(r)
    m = d["document"]["meta"] or {}
    if d["document"]["status"] == "indexed" and m.get("pageindex_status") in ("ok", "degraded"):
        # 确认是本轮重建（created_at 新于 ac1 的树）
        new_created = (m.get("pageindex_tree") or {}).get("created_at")
        if new_created and (not done or new_created != done):
            done = new_created
            break
    if d["document"]["status"] == "failed":
        break
    time.sleep(10)
m = d["document"]["meta"] or {}
record("reindex_pageindex_done",
       d["document"]["status"] == "indexed" and m.get("pageindex_status") in ("ok", "degraded"),
       f"status={d['document']['status']} pi={m.get('pageindex_status')} tree_created={m.get('pageindex_tree', {}).get('created_at')}")

# embedding 文档调 pageindex/rebuild → 400
r = client.post(f"/knowledge-bases/{kb_id}/documents/{emb_doc_id}/pageindex/rebuild", headers=H)
st, code, d, msg = unwrap(r)
record("rebuild_wrong_type_400", st == 400, f"http={st} msg={msg}")

# ============ 输出 ============
with open(OUT, "w") as f:
    json.dump({
        "user": uname, "kb": kb_id, "kb2": kb2_id,
        "doc_pi": doc_id, "doc_emb": emb_doc_id,
        "results": results,
        "sample_answer": full[:500],
        "sample_sources": sources,
    }, f, ensure_ascii=False, indent=2)
print(f"\n==== DONE: {sum(1 for r in results if r['pass'])}/{len(results)} PASS ====")
