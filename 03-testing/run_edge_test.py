#!/usr/bin/env python3
"""边界测试 EDGE-1/2/3
EDGE-1: 大文档多分片建树（>32000 字符，无 heading → 硬切分片）
EDGE-2: 单节点文档（无 heading 短段落）建树 + 检索
EDGE-3: LLM 不可用 → retrieve 错误处理（不静默回退、不抛异常）
"""
import json
import time
import uuid
import base64
import sys

import httpx
from datetime import datetime

BASE = "http://127.0.0.1:9012/api/v1"
TESTDATA = "/home/harry.zhang/kb-management/03-testing/testdata"
OUT = "/home/harry.zhang/kb-management/03-testing/edge_results.json"

results = []


def record(name, ok, detail):
    results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:2000]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {str(detail)[:200]}", flush=True)


def unwrap(r):
    try:
        body = r.json()
    except Exception:
        return r.status_code, None, None, r.text[:300]
    return r.status_code, body.get("code"), body.get("data"), body.get("message")


# ---------- 生成大文档（~90KB，无 heading） ----------
para = (
    "本段落描述系统运行时的资源消耗与容量规划。CPU 占用在检索高峰时段可能上升至 75%，"
    "内存占用与并发文档数量正相关，磁盘 I/O 在批量建树时最为密集。"
    "容量规划应预留至少 40% 的冗余空间以应对流量波动。"
)
# 无 heading，纯段落，约 90KB
large_text = (para + "\n\n") * 450
print(f"large doc chars={len(large_text)}")
large_path = f"{TESTDATA}/large_doc.md"
with open(large_path, "w") as f:
    f.write(large_text)

client = httpx.Client(base_url=BASE, timeout=600)
uname = f"edge_{uuid.uuid4().hex[:8]}"


def _login():
    """注册（可重复）+ 登录，带重试，返回 token。"""
    client.post("/auth/register", json={"username": uname, "email": f"{uname}@example.com",
                                        "password": "Test123456!", "display_name": "边界测试"})
    for _ in range(5):
        b = client.post("/auth/login", json={"username": uname, "password": "Test123456!"}).json()
        tok = (b.get("data") or {}).get("access_token")
        if tok:
            return tok
        time.sleep(2)
    raise RuntimeError(f"login failed for {uname}: {b}")


H = {"Authorization": f"Bearer {_login()}"}

r = client.post("/knowledge-bases", json={"name": "边界KB-" + uname, "description": "edge"}, headers=H)
kb_id = unwrap(r)[2]["id"]

# ============ EDGE-1: 大文档多分片建树 ============
with open(large_path, "rb") as f:
    r = client.post(f"/knowledge-bases/{kb_id}/documents",
                    files={"file": ("large_doc.md", f, "text/markdown")},
                    data={"index_type": "pageindex"}, headers=H)
st, code, d, msg = unwrap(r)
assert st == 200, f"large upload fail {st} {msg}"
large_doc = d["document_id"]
t0 = time.time()
big_state = None
while time.time() - t0 < 1000:
    r = client.get(f"/knowledge-bases/{kb_id}/documents/{large_doc}", headers=H)
    st, code, d, msg = unwrap(r)
    big_state = d
    s = d["document"]["status"]
    pis = (d["document"]["meta"] or {}).get("pageindex_status")
    if s == "indexed" and pis in ("ok", "degraded"):
        break
    if s == "failed":
        break
    time.sleep(15)
m = big_state["document"]["meta"] if big_state else {}
tree = m.get("pageindex_tree") or {}
build_ms = tree.get("build_ms", 0)
record("edge1_large_build_done",
       big_state and big_state["document"]["status"] == "indexed"
       and m.get("pageindex_status") in ("ok", "degraded"),
       f"status={big_state['document']['status'] if big_state else None} "
       f"pi={m.get('pageindex_status')} pieces={tree.get('piece_count')} "
       f"nodes={tree.get('node_count')} build_ms={build_ms} elapsed={int(time.time()-t0)}s")
record("edge1_multipiece",
       tree.get("piece_count", 0) > 1,
       f"piece_count={tree.get('piece_count')} full_text_chars={tree.get('full_text_chars')}")

# ============ EDGE-2: 单节点文档 ============
with open(f"{TESTDATA}/one_node.md", "rb") as f:
    r = client.post(f"/knowledge-bases/{kb_id}/documents",
                    files={"file": ("one_node.md", f, "text/markdown")},
                    data={"index_type": "pageindex"}, headers=H)
st, code, d, msg = unwrap(r)
assert st == 200, f"one_node upload fail {st} {msg}"
onode = d["document_id"]
t0 = time.time()
one_state = None
while time.time() - t0 < 300:
    r = client.get(f"/knowledge-bases/{kb_id}/documents/{onode}", headers=H)
    st, code, d, msg = unwrap(r)
    one_state = d
    s = d["document"]["status"]
    pis = (d["document"]["meta"] or {}).get("pageindex_status")
    if s == "indexed" and pis in ("ok", "degraded"):
        break
    if s == "failed":
        break
    time.sleep(8)
om = one_state["document"]["meta"] if one_state else {}
otree = om.get("pageindex_tree") or {}
record("edge2_onode_build",
       one_state and one_state["document"]["status"] == "indexed"
       and om.get("pageindex_status") in ("ok", "degraded"),
       f"status={one_state['document']['status'] if one_state else None} "
       f"pi={om.get('pageindex_status')} nodes={otree.get('node_count')} "
       f"status_val={otree.get('status')}")
# 检索单节点文档
r = client.post(f"/knowledge-bases/{kb_id}/search", headers=H,
                json={"query": "星尘知识库是什么", "mode": "pageindex", "top_k": 5})
st, code, d, msg = unwrap(r)
items = (d or {}).get("items", [])
record("edge2_onode_search",
       st == 200, f"items={len(items)} msg={d.get('message') if d else None} "
       f"content_head={(items[0]['content'][:50] if items else None)}")

# ============ EDGE-3: LLM 不可用 → 错误处理 ============
# 通过 monkeypatch llm_client.chat 强制 LLM 失败，验证 retrieve 不抛异常、返回 error
sys.path.insert(0, "/home/harry.zhang/kb-management/backend")
from app.services import pageindex_engine as pe
from app.utils import ai_client

orig_chat = ai_client.llm_client.chat


def boom(messages, **kw):
    raise ConnectionError("LLM endpoint unreachable (simulated for EDGE-3)")


ai_client.llm_client.chat = boom
# 同时替换 pe 模块内引用的 llm_client（它是 from import）
pe.llm_client.chat = boom
try:
    res = pe.retrieve(kb_id, "测试问题", top_n=5)
    # res = (results, took_ms, extra)
    r_list, took, extra = res
    record("edge3_llm_unavailable_error",
           isinstance(extra, dict) and "error" in extra and not r_list,
           f"results={len(r_list)} extra={extra}")
except Exception as e:
    record("edge3_llm_unavailable_error", False, f"RETHROW: {type(e).__name__}: {e}")
finally:
    ai_client.llm_client.chat = orig_chat
    pe.llm_client.chat = orig_chat

# 补充：验证"无 pageindex 文档 KB"路径的 error 结构（不静默回退，可观察行为）
r = client.post("/knowledge-bases", json={"name": "空KB-" + uname}, headers=H)
empty_kb = unwrap(r)[2]["id"]
r = client.post(f"/knowledge-bases/{empty_kb}/search", headers=H,
                json={"query": "任意", "mode": "pageindex"})
st, code, d, msg = unwrap(r)
record("edge3_no_silent_fallback",
       st == 200 and (d or {}).get("items") == [] and (d or {}).get("message"),
       f"items={d.get('items')} message={d.get('message')} (无 error 字段=非 LLM 失败路径，属'无文档'提示)")

with open(OUT, "w") as f:
    json.dump({"user": uname, "kb": kb_id, "results": results}, f, ensure_ascii=False, indent=2)
print(f"\n==== EDGE DONE: {sum(1 for r in results if r['pass'])}/{len(results)} PASS ====")
