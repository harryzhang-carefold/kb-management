#!/usr/bin/env bash
# =============================================================================
# 用例: PI-02  pageindex 检索命中正文口令（用例3 第 1 半）
# 卡:   t_32351222 (VI-PI-2)
# 接口: POST /api/v1/knowledge-bases/{kb_id}/search
# 入参(主): {"query":"追溯本次巡检批次时应该用哪个口令定位日志？","mode":"pageindex","top_k":3}
#       KB_ID 默认 32b1101f-efd6-467c-900a-255c75656791（可用 KB_ID 覆盖）
# 首次执行: 2026-10-12T03:3x UTC
# 断言(主查询，任一不满足=FAIL): HTTP 200 且 code=0；total>=1；至少一条 items[].content 含 PI-TOKEN-7412
# 附加(不判 FAIL): 3~5 个不同问法统计命中率（记录数值）
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

KB_ID="${KB_ID:-32b1101f-efd6-467c-900a-255c75656791}"
RAW=03-testing/evidence/raw
TOKEN_MARK="PI-TOKEN-7412"
kb_login || exit 1

echo "==== PI-02 主查询 mode=pageindex top_k=3 ===="
curl -sS -m 120 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -d '{"query":"追溯本次巡检批次时应该用哪个口令定位日志？","mode":"pageindex","top_k":3}' \
  -o "$RAW/PI-02_search_main.json" \
  -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'

echo "[main] $(jq -c '{code,total:.data.total,took_ms:.data.took_ms,message:.data.message,
                     items:[.data.items[]|{filename,md:.metadata,match_type,score,
                       hit:(.content|test("PI-TOKEN-7412"))}]}' "$RAW/PI-02_search_main.json")"

echo "==== PI-02 多问法命中率统计（记录数值，不单独判 FAIL）===="
QS=(
  "追溯本次巡检批次时应该用哪个口令定位日志？"
  "PI-TOKEN-7412 这个口令是做什么用的？"
  "班中抽检发现异常后十五分钟内要做什么？"
  "巡检记录以什么为最小单位？"
  "点检和巡检有什么区别？"
)
HITS=0
N=0
IDX=0
for q in "${QS[@]}"; do
  IDX=$((IDX + 1)); N=$((N + 1))
  body="$(jq -cn --arg q "$q" '{query:$q,mode:"pageindex",top_k:3}')"
  curl -sS -m 120 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KB_TOKEN" \
    -d "$body" \
    -o "$RAW/PI-02_search_q${IDX}.json" \
    -w "HTTP_CODE=%{http_code} TIME=%{time_total}s\n" > "$RAW/PI-02_search_q${IDX}.w"
  h="$(jq -r --arg m "$TOKEN_MARK" '[.data.items[]?.content|test($m)]|map(select(.==true))|length' "$RAW/PI-02_search_q${IDX}.json")"
  tot="$(jq -r '.data.total // 0' "$RAW/PI-02_search_q${IDX}.json")"
  echo "[q$IDX] total=$tot 含口令条目=$h  q=$q"
  if [ "${h:-0}" -gt 0 ]; then HITS=$((HITS + 1)); fi
done
echo "[命中率] $HITS/$N = $(awk "BEGIN{printf \"%.0f%%\", $HITS*100/$N}")"
echo "==== PI-02 DONE ===="
