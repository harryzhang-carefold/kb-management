#!/usr/bin/env python3
"""E2E 测试：登录 → 建库 → 上传 → 等待索引 → 检索 → RAG 问答。"""
import json
import time
import sys
import httpx

BASE = "http://127.0.0.1:9012/api/v1"


def step(name):
    print(f"\n{'='*50}\n📍 {name}\n{'='*50}")


def main():
    c = httpx.Client(timeout=30)

    # 1. Health
    step("1. Health Check")
    r = c.get(f"{BASE}/health")
    d = r.json()
    print(json.dumps(d["data"], indent=2, ensure_ascii=False))
    assert d["code"] == 0

    # 2. Login
    step("2. Login (admin/Admin@123)")
    r = c.post(f"{BASE}/auth/login", json={"username": "admin", "password": "Admin@123"})
    d = r.json()
    assert d["code"] == 0, f"login failed: {d}"
    token = d["data"]["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    print(f"✅ Login OK, user={d['data']['user']['username']}")

    # 3. Create KB
    step("3. Create Knowledge Base")
    r = c.post(f"{BASE}/knowledge-bases", headers=H,
               json={"name": "E2E测试库", "description": "端到端测试", "chunk_size": 400, "chunk_overlap": 40})
    d = r.json()
    assert d["code"] == 0, f"create kb failed: {d}"
    kb_id = d["data"]["id"]
    print(f"✅ KB created: {kb_id}")

    # 4. Upload TXT
    step("4. Upload TXT document")
    content = ("知识库管理系统是一个用于存储、检索和问答的智能系统。它支持文档上传、自动解析、分块、"
               "向量化和全文索引。用户可以使用自然语言提问，系统会基于检索到的片段生成带引用的回答。"
               "部署时需要 PostgreSQL、Elasticsearch、MinIO 和 Redis 四个基础设施组件。")
    r = c.post(f"{BASE}/knowledge-bases/{kb_id}/documents", headers=H,
               files={"file": ("test.txt", content.encode(), "text/plain")})
    d = r.json()
    assert d["code"] == 0, f"upload failed: {d}"
    doc_id = d["data"]["document_id"]
    task_id = d["data"]["task_id"]
    print(f"✅ Uploaded: doc={doc_id} task={task_id}")

    # 5. Poll task status
    step("5. Poll document processing (max 60s)")
    status = ""
    for i in range(30):
        time.sleep(2)
        r = c.get(f"{BASE}/knowledge-bases/{kb_id}/documents/{doc_id}", headers=H)
        d = r.json()
        if d["code"] != 0:
            print(f"error: {d}")
            break
        status = d["data"]["document"]["status"]
        task = d["data"]["task"]
        print(f"  [{i+1}] status={status} task={task['status'] if task else 'N/A'}")
        if status in ("indexed", "failed"):
            break
    print(f"✅ Final status: {status}")
    assert status == "indexed", f"doc not indexed: {status}"

    # 6. Search
    step("6. Hybrid Search: '部署需要哪些组件'")
    r = c.post(f"{BASE}/knowledge-bases/{kb_id}/search", headers=H,
               json={"query": "部署需要哪些组件", "mode": "hybrid", "top_k": 5})
    d = r.json()
    assert d["code"] == 0, f"search failed: {d}"
    items = d["data"]["items"]
    print(f"✅ Found {len(items)} results, took {d['data']['took_ms']}ms")
    for it in items[:3]:
        print(f"  [{it['match_type']}] score={it['score']:.4f} {it['content'][:60]}...")

    # 7. RAG Chat (SSE)
    step("7. RAG Chat (SSE stream): '如何部署这个系统？'")
    full = ""
    sources = []
    with c.stream("POST", f"{BASE}/knowledge-bases/{kb_id}/chat",
                  headers=H,
                  json={"question": "如何部署这个系统？", "top_n": 5}) as resp:
        print(f"  HTTP {resp.status_code}")
        event = ""
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                payload = line[6:]
                if event == "token":
                    full += json.loads(payload).get("token", "")
                elif event == "sources":
                    sources = json.loads(payload).get("sources", [])
                elif event == "done":
                    print(f"  ✅ done: {json.loads(payload)}")
                elif event == "error":
                    print(f"  ❌ error: {payload}")
    print(f"\n  回答({len(full)} chars): {full[:300]}...")
    print(f"  来源: {len(sources)} 个片段")
    assert len(full) > 0, "empty RAG answer"
    assert len(sources) > 0, "no sources"

    # 8. List conversations
    step("8. List conversations")
    r = c.get(f"{BASE}/knowledge-bases/{kb_id}/conversations", headers=H)
    d = r.json()
    assert d["code"] == 0
    print(f"✅ {d['data']['total']} conversation(s)")

    print(f"\n{'='*50}\n🎉 E2E TEST PASSED — 全部 8 步通过\n{'='*50}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ E2E TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
