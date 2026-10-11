"""Final: AC1 tree evidence + AC3 full answer with correct token field."""
import httpx, json

BASE = "http://127.0.0.1:9012/api/v1"
KB_PI = "e7213e59-eb81-4e2f-8760-07fd6778a93a"
DOC_PI = "33010660-d339-48c5-9cf1-e86f56bfeab7"

c = httpx.Client(base_url=BASE, timeout=240)
tok = c.post("/auth/login", json={"username": "testpi_8de322f7",
                                  "password": "Test123456!"}).json()["data"]["access_token"]
H = {"Authorization": f"Bearer {tok}"}

# AC1: full doc meta
r = c.get(f"/knowledge-bases/{KB_PI}/documents", headers=H)
for d in r.json()["data"]["items"]:
    if d["id"] == DOC_PI:
        meta = d["meta"]
        tree = meta.get("pageindex_tree") or {}
        print("AC1 doc:", d["status"], "| index_type=", meta.get("index_type"),
              "| pi_status=", meta.get("pageindex_status"),
              "| node_count=", tree.get("node_count"),
              "| build_ms=", meta.get("pageindex_build_ms"),
              "| built_at=", meta.get("pageindex_built_at"),
              "| piece_count=", meta.get("pageindex_piece_count"),
              "| chunk_count=", d.get("chunk_count"))
        print("  root title:", (tree.get("root") or {}).get("title"))

# AC3: full answer
answer = ""
sources = []
types = []
with c.stream("POST", f"/knowledge-bases/{KB_PI}/chat", headers=H,
              json={"question": "队列积压超过多少条会触发告警？", "retrieval_mode": "pageindex"}, timeout=240) as resp:
    for line in resp.iter_lines():
        if not line:
            continue
        if line.startswith("event:"):
            types.append(line[7:].strip())
        elif line.startswith("data:"):
            j = json.loads(line[6:])
            if "token" in j:
                answer += j["token"]
            if "sources" in j:
                sources = j["sources"]
print("\nAC3 types:", types)
print("AC3 answer:", answer)
print("AC3 sources:", json.dumps(sources, ensure_ascii=False))
json.dump({"answer": answer, "sources": sources},
          open("03-testing/ac3_replay.json", "w"), ensure_ascii=False, indent=2)
