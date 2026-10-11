"""Diagnose: SSE event shapes, doc list shape, EDGE ownership."""
import httpx, json, uuid, time

BASE = "http://127.0.0.1:9012/api/v1"
KB_PI = "e7213e59-eb81-4e2f-8760-07fd6778a93a"
DOC_PI = "33010660-d339-48c5-9cf1-e86f56bfeab7"

def login(username, fresh=False):
    c = httpx.Client(base_url=BASE, timeout=30)
    if fresh:
        u = "replay4_" + uuid.uuid4().hex[:6]
        c.post("/auth/register", json={"username": u, "email": u + "@example.com",
                                       "password": "Test123456!", "display_name": "r"})
        return c, u
    r = c.post("/auth/login", json={"username": username, "password": "Test123456!"})
    return c, username

c, u = login("testpi_8de322f7")
tok = c.post("/auth/login", json={"username": u, "password": "Test123456!"}).json()["data"]["access_token"]
H = {"Authorization": f"Bearer {tok}"}

# 1. doc list (not single-doc endpoint)
r = c.get(f"/knowledge-bases/{KB_PI}/documents", headers=H)
print("doc_list:", r.status_code)
for d in (r.json().get("data") or {}).get("items", []) if isinstance((r.json().get("data") or {}), dict) else []:
    print("  doc:", d.get("id"), d.get("status"), "meta=", json.dumps(d.get("meta") or {}, ensure_ascii=False)[:300])

# 2. raw SSE events for AC3 question
events = []
with c.stream("POST", f"/knowledge-bases/{KB_PI}/chat", headers=H,
              json={"question": "队列积压超过多少条会触发告警？", "retrieval_mode": "pageindex"}, timeout=240) as resp:
    for line in resp.iter_lines():
        if line:
            events.append(line)
print("\nSSE total lines:", len(events))
print("--- first 12 event lines ---")
for e in events[:12]:
    print(repr(e[:120]))
print("--- distinct event types ---")
import collections
types = collections.Counter(e[7:] for e in events if e.startswith("event:"))
print(types)
# dump one chunk-type data payload
for i, e in enumerate(events):
    if e.startswith("event:") and e[7:].strip() in ("chunk", "message", "token", "delta", "response_chunk"):
        nxt = events[i+1] if i+1 < len(events) else ""
        print("\nSAMPLE", e, "=>", nxt[:200])
        break

# 3. EDGE ownership: create fresh KB (no docs) under fresh user, test pageindex search/chat
c2, u2 = login(None, fresh=True)
tok2 = c2.post("/auth/login", json={"username": u2, "password": "Test123456!"}).json()["data"]["access_token"]
H2 = {"Authorization": f"Bearer {tok2}"}
r = c2.post("/knowledge-bases", headers=H2,
            json={"name": "replay_edge_kb", "description": "edge", "index_type": "embedding"})
print("\ncreate KB:", r.status_code, r.text[:200])
kb_edge = (r.json().get("data") or {}).get("id")
if kb_edge:
    r = c2.post(f"/knowledge-bases/{kb_edge}/search", headers=H2,
                json={"query": "星尘知识库是什么", "mode": "pageindex", "top_k": 5})
    dd = r.json().get("data") or {}
    print("EDGE search:", r.status_code, "items=", len(dd.get("items", [])), "msg=", (dd.get("message") or "")[:120])
    ev2 = []
    with c2.stream("POST", f"/knowledge-bases/{kb_edge}/chat", headers=H2,
                   json={"question": "星尘知识库是什么", "retrieval_mode": "pageindex"}, timeout=240) as resp:
        for line in resp.iter_lines():
            if line:
                ev2.append(line)
    errs = [e for e in ev2 if e.startswith("event: error")]
    hints = [e[6:] for e in ev2 if e.startswith("data:") and "没有使用" in e]
    print("EDGE chat:", len(ev2), "lines, error_events=", len(errs), "hint=", len(hints))
    print("   hint sample:", hints[0][:150] if hints else None)
    open("/tmp/edge_kb_id.txt", "w").write(kb_edge)
    open("/tmp/edge_user.txt", "w").write(u2)
