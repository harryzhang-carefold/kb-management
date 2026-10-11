"""A5 新功能验收（A 块侧，端到端 API+curl 等价）。
对**运行中**的 9100 MCP（真实 key 从 infra/.env 读，不打印）与 9012 后端。
覆盖：
  1. MCP search_knowledge / rag_query 返回含 doc_url + location（真实响应样例，脱敏）
  2. 深链 URL 形态正确 + 公网可达（nginx 200 SPA）+ ?token= 调 4 只读端点 200
  3. view_token 拒绝路径：过期 401 / 跨文档 403 / 写端点 401
  4. MCP 鉴权：无 Bearer 401
  5. 9100 常驻：进程在跑 + 172.19.0.1:9100 连通（agent 容器侧等价探测）
浏览器视觉验证留给测试 t_a52daf8a。
"""
import json
import os
import socket
import sys
import uuid

from dotenv import dotenv_values
import httpx

REPO = "/home/harry.zhang/kb-management"
ENV = dotenv_values(f"{REPO}/infra/.env")
MCP_KEY = ENV.get("KB_MCP_API_KEY", "")
assert MCP_KEY, "KB_MCP_API_KEY missing"
PUB_BASE = (ENV.get("KB_PUBLIC_BASE_URL") or "https://agent.carefold.ai/kb-management").rstrip("/")

# 与运行中 9012 同 SECRET_KEY 的 view_token 签发（复用后端实现）
sys.path.insert(0, f"{REPO}/backend")
os.environ.setdefault("KB_MCP_API_KEY", MCP_KEY)
from app.core.security import create_view_token, decode_view_token  # noqa: E402
from app.core.config import settings  # noqa: E402
print("secret_key loaded:", bool(settings.secret_key) and settings.secret_key != "change-me")

MCP_BASE = "http://127.0.0.1:9100/mcp"
API = "http://127.0.0.1:9012/api/v1"


def mcp_call(name, args, key=MCP_KEY):
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if key is not None:
        h["Authorization"] = f"Bearer {key}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": args}}
    r = httpx.post(MCP_BASE, json=body, headers=h, timeout=120)
    ct = r.headers.get("content-type", "")
    if "text/event-stream" in ct:
        data_lines = [l[5:].strip() for l in r.text.splitlines() if l.startswith("data: ")]
        try:
            return r.status_code, [json.loads(d) for d in data_lines if d.startswith("{")]
        except json.JSONDecodeError:
            return r.status_code, r.text[:800]
    return r.status_code, r.text[:1500]


def extract_result_text(code, body):
    """从 tools/call 响应里取出工具返回的 JSON 文本。"""
    if isinstance(body, list):
        for b in body:
            if isinstance(b, dict) and b.get("result", {}).get("content"):
                c = b["result"]["content"]
                if c and isinstance(c[0], dict) and "text" in c[0]:
                    return c[0]["text"]
    if isinstance(body, str):
        return body
    return None


def mask(tok):
    if not tok:
        return tok
    return tok[:12] + "..." + tok[-4:] if len(tok) > 20 else tok[:4] + "..."


results = {}

# ===== 1. MCP 鉴权：无 Bearer 401 =====
code, body = mcp_call("list_knowledge_bases", {}, key=None)
results["mcp_no_bearer"] = (code, str(body)[:120])

# ===== 2. MCP search_knowledge 含 doc_url+location =====
code, body = mcp_call("search_knowledge", {"query": "regression quick brown fox", "top_k": 5})
sk_text = extract_result_text(code, body)
sk = {}
try:
    sk = json.loads(sk_text) if sk_text else {}
except Exception as e:
    results["search_parse_err"] = str(e)[:200]
items = sk.get("items", [])
first = items[0] if items else {}
results["mcp_search"] = {
    "http": code,
    "total": sk.get("total"),
    "first_has_doc_url": bool(first.get("doc_url")),
    "first_has_location": bool(first.get("location")),
    "first_location": first.get("location"),
    "first_doc_url_masked": mask(first.get("doc_url", "")),
    "first_doc_id": first.get("document_id"),
    "first_filename": first.get("filename"),
}

# ===== 3. MCP rag_query 含 doc_url+location =====
code, body = mcp_call("rag_query", {"question": "regression 文档里提到 quick brown fox 吗？"})
rq_text = extract_result_text(code, body)
rq = {}
try:
    rq = json.loads(rq_text) if rq_text else {}
except Exception as e:
    results["rag_parse_err"] = str(e)[:200]
sources = rq.get("sources", [])
fs = sources[0] if sources else {}
results["mcp_rag"] = {
    "http": code,
    "answer_len": len(rq.get("answer", "")),
    "n_sources": len(sources),
    "first_source_has_doc_url": bool(fs.get("doc_url")),
    "first_source_location": fs.get("location"),
    "first_source_doc_url_masked": mask(fs.get("doc_url", "")),
    "first_source_name": fs.get("filename") or fs.get("source"),
}

# 深链 URL 校验：从 search/rag 拿一个真实 doc_url
doc_url = first.get("doc_url") or fs.get("doc_url")
if not doc_url:
    for s in sources:
        if s.get("doc_url"):
            doc_url = s["doc_url"]
            break
if not doc_url:
    for it in items:
        if it.get("doc_url"):
            doc_url = it["doc_url"]
            break

results["deeplink_shape"] = {
    "doc_url_present": bool(doc_url),
    "starts_with_pub_base": (doc_url or "").startswith(PUB_BASE),
    "has_kb_doc_path": "/kb/" in (doc_url or "") and "/doc/" in (doc_url or ""),
    "has_token_param": "token=" in (doc_url or ""),
    "has_locator": ("chunk=" in (doc_url or "")) or ("node=" in (doc_url or "")),
    "doc_url_masked": mask(doc_url or ""),
}

# ===== 4. 公网可达（nginx 200 SPA）=====
# 深链去掉 token 走 nginx 应 200（SPA fallback）；带 token 也 200（同一路由）
deeplink_no_tok = (doc_url or "").split("?")[0]
r = httpx.get(deeplink_no_tok, timeout=20, follow_redirects=True)
results["public_spa"] = {"url_no_tok_masked": mask(deeplink_no_tok), "http": r.status_code,
                          "is_html": "text/html" in r.headers.get("content-type", "")}

# ===== 5. ?token= 调 4 只读端点 200 =====
# 从 doc_url 解析 kb_id / doc_id / token / chunk
tok = ""
kb_id = doc_id = chunk = None
try:
    import urllib.parse
    q = urllib.parse.urlparse(doc_url)
    path = q.path.split("/")  # .../kb/<kb>/doc/<doc>
    kb_id = path[path.index("kb") + 1]
    doc_id = path[path.index("doc") + 1]
    qs = urllib.parse.parse_qs(q.query)
    tok = qs.get("token", [""])[0]
    chunk = qs.get("chunk", qs.get("node", [""]))[0]
except Exception as e:
    results["deeplink_parse_err"] = str(e)[:200]

api = httpx.Client(base_url=API, timeout=30)


def api_get(ep, tok, retries=3):
    for i in range(retries):
        try:
            return api.get(ep, params={"token": tok})
        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            if i == retries - 1:
                return None
            import time
            time.sleep(1.5 * (i + 1))
    return None


def api_delete(ep, tok, retries=3):
    for i in range(retries):
        try:
            return api.delete(ep, params={"token": tok})
        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            if i == retries - 1:
                return None
            import time
            time.sleep(1.5 * (i + 1))
    return None


ro_endpoints = {
    "detail": f"/knowledge-bases/{kb_id}/documents/{doc_id}",
    "download": f"/knowledge-bases/{kb_id}/documents/{doc_id}/download",
    "content": f"/knowledge-bases/{kb_id}/documents/{doc_id}/content",
    "chunks": f"/knowledge-bases/{kb_id}/documents/{doc_id}/chunks",
}
ro_res = {}
for name, ep in ro_endpoints.items():
    r = api_get(ep, tok)
    if r is None:
        ro_res[name] = {"http": "RESET", "note": "connection reset after retries"}
        continue
    cd = r.headers.get("content-disposition", "")
    ct = r.headers.get("content-type", "")
    ro_res[name] = {"http": r.status_code, "cd": cd[:60], "ct": ct[:40]}
results["view_token_readonly"] = ro_res

# ===== 6. view_token 拒绝路径 =====
# 6a. 过期：签发一个已过期 token（minutes 用负数→exp 过去）
expired = create_view_token(doc_id, kb_id, viewer="test", minutes=-1)
r = api_get(f"/knowledge-bases/{kb_id}/documents/{doc_id}", expired)
results["rejection_expired_401"] = ({"http": r.status_code, "body": r.text[:120]} if r else {"http": "RESET"})

# 6b. 跨文档：doc_id 的 token 访问另一文档
other_doc = None
for it in items[1:]:
    if it.get("document_id") and it["document_id"] != doc_id:
        other_doc = it["document_id"]
        break
if not other_doc:
    # 兜底：造一个假 doc_id（uuid）
    other_doc = str(uuid.uuid4())
    other_tok = create_view_token(other_doc, kb_id, viewer="test")
    r = api_get(f"/knowledge-bases/{kb_id}/documents/{other_doc}", other_tok)
    results["rejection_crossdoc_403"] = ({"http": r.status_code, "body": r.text[:120], "note": "synthetic other doc"} if r else {"http": "RESET"})
else:
    # 用 doc_id 的 token 访问 other_doc（同 kb 跨文档 → 403）
    r = api_get(f"/knowledge-bases/{kb_id}/documents/{other_doc}", tok)
    results["rejection_crossdoc_403"] = ({"http": r.status_code, "body": r.text[:120], "other_doc": other_doc} if r else {"http": "RESET"})

# 6c. 跨 KB：doc_id 的 token 访问另一个 kb 下的同 doc_id
code, body = mcp_call("list_knowledge_bases", {})
lst_text = extract_result_text(code, body)
kbs = json.loads(lst_text).get("items", []) if lst_text else []
other_kb = None
for kb in kbs:
    if kb.get("id") != kb_id:
        other_kb = kb.get("id")
        break
if other_kb:
    r = api_get(f"/knowledge-bases/{other_kb}/documents/{doc_id}", tok)
    results["rejection_crosskb_403"] = ({"http": r.status_code, "body": r.text[:120], "other_kb": other_kb} if r else {"http": "RESET"})
else:
    results["rejection_crosskb_403"] = {"http": None, "note": "no other kb, skipped"}

# 6d. 写端点 401：view_token 调 DELETE（应 401，非 access 型）
r = api_delete(f"/knowledge-bases/{kb_id}/documents/{doc_id}", tok)
results["rejection_write_endpoint_401"] = ({"http": r.status_code, "body": r.text[:120]} if r else {"http": "RESET"})

# ===== 7. 9100 常驻 =====
import subprocess
ps = subprocess.run(["pgrep", "-f", "mcp_server:streamable_app"], capture_output=True, text=True)
pids = ps.stdout.split()
results["mcp_9100_process"] = {"running": len(pids) > 0, "pids": pids}
# 172.19.0.1:9100 连通（agent 容器侧等价：bridge IP 直连）
try:
    s = socket.create_connection(("172.19.0.1", 9100), timeout=5)
    s.close()
    results["agent_side_172_19"] = {"tcp_open": True}
except Exception as e:
    results["agent_side_172_19"] = {"tcp_open": False, "err": str(e)[:100]}

print(json.dumps(results, ensure_ascii=False, indent=2))
api.close()
print("A5 ACCEPTANCE DONE")
