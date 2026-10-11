#!/usr/bin/env bash
set -e
# 用例: TC-AC2  pageindex 检索 — 返回相关段落（document_id/content/score）
# 接口: POST /api/v1/knowledge-bases/{KB_ID}/search
# 入参: {query:"模型服务不可用时应该怎么排查？", mode:pageindex, top_k:5}
# 首次执行: 2026-10-10  结果: PASS (HTTP 200, items=3, match_type=pageindex, score=1.0)
# 复测: KB_ID 换成含 pageindex 索引文档的 KB（见 03-testing/api_results.json kb 字段）
BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"
KB_ID="${KB_ID:-e7213e59-eb81-4e2f-8760-07fd6778a93a}"
TOKEN="${TOKEN:-${KB_TOKEN:-}}" # 来源: POST /api/v1/auth/login
curl -sS -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"query":"模型服务不可用时应该怎么排查？","mode":"pageindex","top_k":5}' -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'
