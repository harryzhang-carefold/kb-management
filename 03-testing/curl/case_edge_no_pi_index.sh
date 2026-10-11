#!/usr/bin/env bash
set -e
# 用例: TC-EDGE  边界 — 无 pageindex 文档 KB 做 pageindex 检索/问答（空结果+提示，不静默回退）
# 接口: POST /api/v1/knowledge-bases/{KB_ID}/search 与 /chat
# 入参: search {query:星尘知识库是什么, mode:pageindex}; chat {question:同, retrieval_mode:pageindex}
# 首次执行: 2026-10-10  结果: PASS (search: items=[] + message; chat: SSE error 事件 + 同提示)
# 注意: KB_ID 需为不含任何 pageindex 索引文档的 KB（见 api_results.json kb2 字段）
BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"
KB_ID="${KB_ID:-ca3dedd7-6345-47f6-b02b-3ea522f6b189}"
TOKEN="${TOKEN:-${KB_TOKEN:-}}"
echo "===== search mode=pageindex（无索引文档） ====="
curl -sS -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"query":"星尘知识库是什么","mode":"pageindex"}' -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'
echo "===== chat retrieval_mode=pageindex（无索引文档） ====="
curl -sS -N -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/chat" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"星尘知识库是什么","retrieval_mode":"pageindex"}' -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'
