#!/usr/bin/env bash
# =============================================================================
# 用例: PI-03  pageindex 问答（SSE）sources 正常（用例3 第 2 半）
# 卡:   t_32351222 (VI-PI-2)
# 接口: POST /api/v1/knowledge-bases/{kb_id}/chat   (SSE, text/event-stream)
# 入参(主): {"question":"追溯本次巡检批次时应该用哪个口令定位日志？","retrieval_mode":"pageindex","top_n":3}
#       KB_ID 默认 32b1101f-efd6-467c-900a-255c75656791（可用 KB_ID 覆盖）
# 首次执行: 2026-10-12T03:3x UTC
# 断言(主查询，任一不满足=FAIL):
#   B1 HTTP 200 且事件序列包含 meta → (token 多次) → sources → done
#   B2 sources >= 1
#   B3 答案非空，且含 PI-TOKEN-7412 或至少正确引用参考片段
# 附加(观察项，不判 FAIL): 同一文档不传 retrieval_mode（走 schema 默认）时的 sources 数
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

KB_ID="${KB_ID:-32b1101f-efd6-467c-900a-255c75656791}"
RAW=03-testing/evidence/raw
kb_login || exit 1

echo "==== PI-03 主查询 retrieval_mode=pageindex top_n=3 (SSE) ===="
curl -sS -N -m 180 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -d '{"question":"追溯本次巡检批次时应该用哪个口令定位日志？","retrieval_mode":"pageindex","top_n":3}' \
  -o "$RAW/PI-03_chat_main.sse" \
  -D "$RAW/PI-03_chat_main.headers" \
  -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'

echo "[headers] $(grep -i '^HTTP/\|^content-type' "$RAW/PI-03_chat_main.headers" | tr -d '\r' | tr '\n' ' ')"
echo "[event-sequence] $(grep '^event:' "$RAW/PI-03_chat_main.sse" | awk '{print $2}' | tr '\n' ' ')"
echo "[event-counts] $(grep '^event:' "$RAW/PI-03_chat_main.sse" | awk '{print $2}' | sort | uniq -c | tr '\n' ' ')"
echo "[sources] $(grep -A1 '^event: sources' "$RAW/PI-03_chat_main.sse" | grep '^data:' | sed 's/^data: //')"
echo "[answer] $(grep -A1 '^event: token' "$RAW/PI-03_chat_main.sse" | grep '^data:' | sed 's/^data: //' | jq -r '.token' 2>/dev/null | tr -d '\n')"
echo ""

echo "==== PI-03 观察项：不传 retrieval_mode（走默认）时的 sources ===="
curl -sS -N -m 180 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -d '{"question":"追溯本次巡检批次时应该用哪个口令定位日志？","top_n":3}' \
  -o "$RAW/PI-03_chat_defaultmode.sse" \
  -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'
echo "[obs-events] $(grep '^event:' "$RAW/PI-03_chat_defaultmode.sse" | awk '{print $2}' | tr '\n' ' ')"
echo "[obs-meta] $(grep -A1 '^event: meta' "$RAW/PI-03_chat_defaultmode.sse" | grep '^data:' | sed 's/^data: //')"
echo "[obs-sources] $(grep -A1 '^event: sources' "$RAW/PI-03_chat_defaultmode.sse" | grep '^data:' | sed 's/^data: //')"
echo "==== PI-03 DONE ===="
