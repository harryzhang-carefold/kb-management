"""Replay archived curl cases for t_553f17d8 verification (run 24).
Replays AC2/AC3/AC4/EDGE with the exact params from 03-testing/curl/*.sh.
Writes results to 03-testing/replay_results.json. Read-only: no code changes.
"""
import httpx, json, uuid, time, sys

BASE = "http://127.0.0.1:9012/api/v1"
KB_PI = "e7213e59-eb81-4e2f-8760-07fd6778a93a"   # has pageindex doc 33010660
KB_EDGE = "ca3dedd7-6345-47f6-b02b-3ea522f6b189" # no pageindex doc
DOC_PI = "33010660-d339-48c5-9cf1-e86f56bfeab7"

c = httpx.Client(base_url=BASE, timeout=120)

# fresh token (new user to be safe)
u = "replay3_" + uuid.uuid4().hex[:6]
r = c.post("/auth/register", json={"username": u, "email": u + "@example.com",
                                   "password": "Test123456!", "display_name": "r"})
assert r.status_code == 200, f"register failed: {r.text[:200]}"
r = c.post("/auth/login", json={"username": u, "password": "Test123456!"})
tok = r.json()["data"]["access_token"]
print("user", u, "tok_len", len(tok))

H = {"Authorization": f"Bearer {tok}"}
results = []

def check(name, cond, detail):
    results.append({"name": name, "pass": bool(cond), "detail": str(detail)[:400]})
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {detail}")

# ---- doc status (AC-1 evidence) ----
r = c.get(f"/knowledge-bases/{KB_PI}/documents/{DOC_PI}", headers=H)
d = (r.json().get("data") or {})
meta = d.get("meta") or {}
print("doc status:", r.status_code, d.get("status"),
      "pi_status=", meta.get("pageindex_status"),
      "nodes=", (meta.get("pageindex_tree") or {}).get("node_count") if meta.get("pageindex_tree") else None,
      "chunk_count=", d.get("chunk_count"), "index_type=", meta.get("index_type"))
check("ac1_doc_indexed", r.status_code == 200 and d.get("status") == "indexed",
      f"status={d.get('status')} pi_status={meta.get('pageindex_status')} chunk_count={d.get('chunk_count')}")

# ---- AC2: search mode=pageindex ----
t0 = time.time()
r = c.post(f"/knowledge-bases/{KB_PI}/search", headers=H,
           json={"query": "模型服务不可用时应该怎么排查？", "mode": "pageindex", "top_k": 5})
el = time.time() - t0
b = r.json()
items = (b.get("data") or {}).get("items", [])
first = items[0] if items else {}
print("AC2:", r.status_code, "items=", len(items), "took_ms=", (b.get("data") or {}).get("took_ms"), "elapsed=", round(el, 1))
check("ac2_200", r.status_code == 200 and b.get("code") == 0, f"http={r.status_code} code={b.get('code')}")
check("ac2_items_relevant", len(items) > 0 and first.get("document_id") == DOC_PI and first.get("content"),
      f"n={len(items)} first_doc={first.get('document_id')} score={first.get('score')} mt={first.get('match_type')} content_head={str(first.get('content'))[:60]}")

# ---- AC3: chat retrieval_mode=pageindex (SSE) ----
def sse_chat(kb, q, rm):
    events = []
    with c.stream("POST", f"/knowledge-bases/{kb}/chat", headers=H,
                  json={"question": q, "retrieval_mode": rm}, timeout=180) as resp:
        status = resp.status_code
        for line in resp.iter_lines():
            if line:
                events.append(line)
    return status, events

t0 = time.time()
status, events = sse_chat(KB_PI, "队列积压超过多少条会触发告警？", "pageindex")
el = time.time() - t0
ev_lines = [e for e in events if e.startswith("event:")]
data_lines = [e[6:] for e in events if e.startswith("data:")]
n_data = len(data_lines)
sources = []
answer_parts = []
for dl in data_lines:
    try:
        j = json.loads(dl)
    except Exception:
        continue
    et = j.get("type", "")
    if et in ("source", "sources") or "sources" in j:
        s = j.get("sources") or (j if "filename" in j else None)
        if isinstance(s, list):
            sources.extend(s)
        elif isinstance(s, dict):
            sources.append(s)
    if et == "chunk" or "text" in j:
        answer_parts.append(j.get("text") or j.get("content") or "")
answer = "".join(answer_parts)
print("AC3:", status, "data_events=", n_data, "elapsed=", round(el, 1),
      "sources=", len(sources), "answer=", answer[:100])
check("ac3_sse_200", status == 200, f"http={status} events={n_data}")
check("ac3_streaming", n_data > 5, f"data_events={n_data} (streaming)")
check("ac3_sources", len(sources) > 0 and all(k in sources[0] for k in ("document_id", "filename", "score", "chunk_id", "chunk_index")),
      f"n_sources={len(sources)} keys={list(sources[0].keys()) if sources else []}")
check("ac3_citation", ("200" in answer and ("[1]" in answer or "告警" in answer)),
      f"answer_head={answer[:100]}")

# ---- AC4: regression hybrid/vector/keyword ----
for mode in ("hybrid", "vector", "keyword"):
    r = c.post(f"/knowledge-bases/{KB_PI}/search", headers=H,
               json={"query": "告警分级", "mode": mode, "top_k": 5})
    b = r.json()
    print("AC4", mode, ":", r.status_code, "code=", b.get("code"),
          "items=", len((b.get("data") or {}).get("items", [])))
    check(f"ac4_{mode}", r.status_code == 200 and b.get("code") == 0,
          f"http={r.status_code} code={b.get('code')} items={len((b.get('data') or {}).get('items', []))}")
# invalid mode -> 422
r = c.post(f"/knowledge-bases/{KB_PI}/search", headers=H,
           json={"query": "x", "mode": "badmode", "top_k": 5})
check("ac4_mode_validation_422", r.status_code == 422, f"http={r.status_code}")

# ---- EDGE: KB without pageindex doc ----
r = c.post(f"/knowledge-bases/{KB_EDGE}/search", headers=H,
           json={"query": "星尘知识库是什么", "mode": "pageindex", "top_k": 5})
b = r.json()
dd = b.get("data") or {}
print("EDGE search:", r.status_code, "items=", len(dd.get("items", [])), "message=", dd.get("message"))
check("edge_search_empty_hint", r.status_code == 200 and len(dd.get("items", [])) == 0 and "PageIndex" in (dd.get("message") or ""),
      f"items={len(dd.get('items', []))} msg={dd.get('message')[:80]}")

status, events = sse_chat(KB_EDGE, "星尘知识库是什么", "pageindex")
err_events = [e for e in events if e.startswith("event: error")]
err_data = [e[6:] for e in events if e.startswith("data:") and "该知识库下没有使用" in e]
print("EDGE chat:", status, "error_events=", len(err_events), "hint_data=", len(err_data))
check("edge_chat_error_hint", status == 200 and len(err_events) >= 1 and len(err_data) >= 1,
      f"error_events={len(err_events)} hint={err_data[0][:80] if err_data else None}")

json.dump({"user": u, "kb_pi": KB_PI, "kb_edge": KB_EDGE, "results": results,
           "ac3_answer": answer[:500], "ac3_sources": sources[:5]},
          open("03-testing/replay_results.json", "w"), ensure_ascii=False, indent=2)
npass = sum(1 for x in results if x["pass"])
print(f"\nTOTAL: {npass}/{len(results)} PASS")
sys.exit(0 if npass == len(results) else 1)
