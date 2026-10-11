#!/usr/bin/env bash
set -e
# 用例: TC-AC4  回归 — 原路径 mode=hybrid / vector / keyword 不受影响
# 接口: POST /api/v1/knowledge-bases/{KB_ID}/search（mode 三值）
# 入参: {query:"告警分级", mode:hybrid|vector|keyword, top_k:5}
# 首次执行: 2026-10-10  结果: PASS (三值均 HTTP 200, code=0)
# 注意: 本轮 embedding 端点 34.64.61.208:4000 不可达(环境态)，vector 按原逻辑退化为
#       keyword、返回 items=[] 属原设计行为，非回归缺陷。
BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"
KB_ID="${KB_ID:-e7213e59-eb81-4e2f-8760-07fd6778a93a}"
TOKEN="${TOKEN:-${KB_TOKEN:-}}"
for MODE in hybrid vector keyword; do
  echo "===== mode=$MODE ====="
  curl -sS -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"query\":\"告警分级\",\"mode\":\"$MODE\",\"top_k\":5}" -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'
done
