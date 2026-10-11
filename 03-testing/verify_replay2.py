"""Replay round 2: use ORIGINAL user's fresh token (KB owner = testpi_8de322f7).
With retries for transient connection resets. Read-only.
"""
import httpx, json, uuid, time, sys

BASE = "http://127.0.0.1:9012/api/v1"
KB_PI = "e7213e59-eb81-4e2f-8760-07fd6778a93a"
KB_EDGE = "ca3dedd7-6345-47f6-b02b-3ea522f6b189"
DOC_PI = "33010660-d339-48c5-9cf1-e86f56bfeab7"
EDGE_USER = "edge_c0338852"

def login(username):
    c = httpx.Client(base_url=BASE, timeout=30)
    r = c.post("/auth/login", json={"username": username, "password": "Test123456!"})
    b = r.json()
    return r.status_code, (b.get("data") or {}).get("access_token")

def with_retry(fn, name, tries=4, delay=15):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            print(f"  retry {i+1}/{tries} for {name}: {type(e).__name__}: {str(e)[:100]}")
            if i == tries - 1:
                raise
            time.sleep(delay)

c = httpx.Client(base_url=BASE, timeout=240)
st, tok = login("testpi_8de322f7")
print("owner login", st, "tok_len", len(tok) if tok else None)
st2, tok_e = login(EDGE_USER)
print("edge login", st2, "tok_len", len(tok_e) if tok_e else None)
H = {"Authorization": f"Bearer {tok}"}
He = {"Authorization": f"Bearer {tok_e}"}
results = []

def check(name, cond, detail):
    results.append({"name": name, "pass": bool(cond), "detail": str(detail)[:400]})
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {detail}")

# AC-1 evidence: doc status (owner token)
def _doc():
    r = c.get(f"/knowledge-bases/{KB_PI}/documents/{DOC_PI}", headers=H)
    return r
try:
    r = with_retry(_doc, "doc_status")
    d = r.json().get("data") or {}
    meta = d.get("meta") or {}
    tree = meta.get("pageindex_tree") or {}
    print("doc:", r.status_code, d.get("status"), "pi=", meta.get("pageindex_status"),
          "nodes=", tree.get("node_count"), "chunks=", d.get("chunk_count"),
          "idx_type=", meta.get("index_type"), "build_ms=", meta.get("pageindex_build_ms"))
    check("ac1_doc_indexed", r.status_code == 200 and d.get("status") == "indexed"
          and meta.get("index_type") == "pageindex" and (d.get("chunk_count") == 0),
          f"status={d.get('status')} pi={meta.get('pageindex_status')} nodes={tree.get('node_count')} chunks={d.get('chunk_count')}")
except Exception as e:
    check("ac1_doc_indexed", False, f"error: {type(e).__name__}: {str(e)[:150]}")

# AC2
def _ac2():
    t0 = time.time()
    r = c.post(f"/knowledge-bases/{KB_PI}/search", headers=H,
               json={"query": "模型服务不可用时应该怎么排查？", "mode": "pageindex", "top_k": 5})
    el = time.time() - t0
    return r, el
try:
    r, el = with_retry(_ac2, "ac2")
    b = r.json()
    dd = b.get("data") or {}
    items = dd.get("items", [])
    first = items[0] if items else {}
    print("AC2:", r.status_code, "items=", len(items), "took_ms=", dd.get("took_ms"), "elapsed=", round(el, 1))
    for it in items[:3]:
        print("   item:", it.get("document_id"), "score=", it.get("score"), "mt=", it.get("match_type"),
              "meta=", str(it.get("metadata"))[:90], "content=", str(it.get("content"))[:60])
    check("ac2_200", r.status_code == 200 and b.get("code") == 0, f"http={r.status_code} code={b.get('code')}")
    check("ac2_items_relevant", len(items) > 0 and first.get("document_id") == DOC_PI and first.get("content"),
          f"n={len(items)} first_doc={first.get('document_id')} score={first.get('score')} mt={first.get('match_type')} head={str(first.get('content'))[:60]}")
except Exception as e:
    check("ac2_200", False, f"error: {type(e).__name__}: {str(e)[:150]}")

# AC3 (SSE)
def _sse(kb, q, rm, hdr):
    events = []
    with c.stream("POST", f"/knowledge-bases/{kb}/chat", headers=hdr,
                  json={"question": q, "retrieval_mode": rm}, timeout=240) as resp:
        for line in resp.iter_lines():
            if line:
                events.append(line)
    return resp.status_code, events

def _ac3():
    t0 = time.time()
    stt, ev = _sse(KB_PI, "队列积压超过多少条会触发告警？", "pageindex", H)
    return stt, ev, time.time() - t0

sources, answer = [], ""
try:
    status, events, el = with_retry(_ac3, "ac3")
    data_lines = [e[6:] for e in events if e.startswith("data:")]
    for dl in data_lines:
        try:
            j = json.loads(dl)
        except Exception:
            continue
        if "sources" in j and isinstance(j["sources"], list):
            sources.extend(j["sources"])
        if "text" in j:
            answer += j["text"]
    print("AC3:", status, "events=", len(events), "data=", len(data_lines), "elapsed=", round(el, 1))
    print("   answer:", answer[:150])
    print("   sources:", json.dumps(sources[:3], ensure_ascii=False)[:250])
    check("ac3_sse_200", status == 200, f"http={status} events={len(events)}")
    check("ac3_streaming", len(data_lines) > 5, f"data_events={len(data_lines)}")
    check("ac3_sources", len(sources) > 0 and all(k in sources[0] for k in ("document_id", "filename", "score", "chunk_id", "chunk_index")),
          f"n={len(sources)} keys={list(sources[0].keys()) if sources else []}")
    check("ac3_citation", "200" in answer and "[1]" in answer and "P2" in answer,
          f"answer_head={answer[:100]}")
except Exception as e:
    for n in ("ac3_sse_200", "ac3_streaming", "ac3_sources", "ac3_citation"):
        check(n, False, f"error: {type(e).__name__}: {str(e)[:150]}")

# AC4
for mode in ("hybrid", "vector", "keyword"):
    def _ac4(m=mode):
        return c.post(f"/knowledge-bases/{KB_PI}/search", headers=H,
                      json={"query": "告警分级", "mode": m, "top_k": 5})
    try:
        r = with_retry(_ac4, f"ac4_{mode}")
        b = r.json()
        n = len((b.get("data") or {}).get("items", []))
        print("AC4", mode, ":", r.status_code, "code=", b.get("code"), "items=", n)
        check(f"ac4_{mode}", r.status_code == 200 and b.get("code") == 0, f"http={r.status_code} code={b.get('code')} items={n}")
    except Exception as e:
        check(f"ac4_{mode}", False, f"error: {type(e).__name__}: {str(e)[:150]}")

def _bad():
    return c.post(f"/knowledge-bases/{KB_PI}/search", headers=H,
                  json={"query": "x", "mode": "badmode", "top_k": 5})
try:
    r = with_retry(_bad, "badmode")
    check("ac4_mode_validation_422", r.status_code == 422, f"http={r.status_code}")
except Exception as e:
    check("ac4_mode_validation_422", False, f"error: {type(e).__name__}: {str(e)[:150]}")

# EDGE (user edge_c0338852 owns KB_EDGE per edge_results.json)
def _esearch():
    return c.post(f"/knowledge-bases/{KB_EDGE}/search", headers=He,
                  json={"query": "星尘知识库是什么", "mode": "pageindex", "top_k": 5})
try:
    r = with_retry(_esearch, "edge_search")
    b = r.json()
    dd = b.get("data") or {}
    msg = dd.get("message") or ""
    print("EDGE search:", r.status_code, "items=", len(dd.get("items", [])), "msg=", msg[:90])
    check("edge_search_empty_hint", r.status_code == 200 and len(dd.get("items", [])) == 0 and "PageIndex" in msg,
          f"items={len(dd.get('items', []))} msg={msg[:90]}")
except Exception as e:
    check("edge_search_empty_hint", False, f"error: {type(e).__name__}: {str(e)[:150]}")

def _echat():
    return _sse(KB_EDGE, "星尘知识库是什么", "pageindex", He)
try:
    status, events = with_retry(_echat, "edge_chat")
    err_ev = [e for e in events if e.startswith("event: error")]
    hint = [e[6:] for e in events if e.startswith("data:") and "该知识库下没有使用" in e]
    print("EDGE chat:", status, "error_events=", len(err_ev), "hint=", len(hint))
    check("edge_chat_error_hint", status == 200 and len(err_ev) >= 1 and len(hint) >= 1,
          f"err_events={len(err_ev)} hint={hint[0][:90] if hint else None}")
except Exception as e:
    check("edge_chat_error_hint", False, f"error: {type(e).__name__}: {str(e)[:150]}")

json.dump({"owner": "testpi_8de322f7", "kb_pi": KB_PI, "kb_edge": KB_EDGE,
           "results": results, "ac3_answer": answer[:500], "ac3_sources": sources[:5]},
          open("03-testing/replay_results2.json", "w"), ensure_ascii=False, indent=2)
npass = sum(1 for x in results if x["pass"])
print(f"\nTOTAL: {npass}/{len(results)} PASS")
sys.exit(0 if npass == len(results) else 1)
