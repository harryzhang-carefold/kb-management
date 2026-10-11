#!/usr/bin/env bash
set -e
# 用例: TC-AC3  pageindex 问答 — SSE 流式回答 + 引用来源标注
# 接口: POST /api/v1/knowledge-bases/{KB_ID}/chat
# 入参: {question:"队列积压超过多少条会触发告警？", retrieval_mode:pageindex}
# 首次执行: 2026-10-10  结果: PASS (HTTP 200, SSE 52 事件, 回答含 "200 条…P2 级告警 [1]")
BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"
KB_ID="${KB_ID:-e7213e59-eb81-4e2f-8760-07fd6778a93a}"
TOKEN="${TOKEN:-${KB_TOKEN:-}}" # 来源: POST /api/v1/auth/login
curl -sS -N -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/chat" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"队列积压超过多少条会触发告警？","retrieval_mode":"pageindex"}' -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'
