#!/usr/bin/env bash
# =============================================================================
# 用例: PI-09  [PI-V4] 线上 UI 默认上传的 pageindex 文档——pageindex 模式检索可用性
# 卡:   t_2ba41218 (VI-PI-4, 验证链第 4 段)   对应任务步骤 A5 第 1 半
# 接口: POST /api/v1/knowledge-bases/{kb_id}/search
# 入参(主): {"query":"追溯本次巡检批次时应该用哪个口令定位日志？","mode":"pageindex","top_k":3}
#       KB_ID 默认 22bcb345-8326-479c-958b-51daa2905715（VI-PI-4 自建 KB，
#              文档由「线上 UI 不点 radio 直接上传」产生，非 curl 上传）
# 鉴权: 走 lib/kb_common.sh 的 kb_post（token 由 kb_login 注入，脚本内不出现凭据）
# 说明: 命令形状与第 2 段 case_PI-02_search_pageindex.sh 一致，仅 KB_ID 不同（另存以免覆盖第 2 段 raw）。
#       主查询重复 3 次：2026-10-12 首次执行发现 pageindex 检索会间歇性 0 命中
#       （同 query 同 KB 复跑即可复现；第 2 段对照 KB 亦然，见 PI-V4_raw/DIAG3_console.txt）。
#       故按「不稳定即缺陷」口径：任一 run 为 0 → 本用例 FAIL（不放水）。
# 首次执行: 2026-10-12T04:02:41Z（单次）→ 2026-10-12T04:06:54~04:07:03Z（×3 版）
# 首次结果: 3 次 total = 2 / 0 / 0 → 1/3 命中（不稳定）；详见 PI-V4_case2_case6.txt 与 PI-V4_result.json
# 断言（任一不满足=FAIL）:
#   S1 每次 HTTP 200 且 code=0
#   S2 每次 total >= 1（3/3 稳定命中）
#   S3 至少一条 items[].content 含 PI-TOKEN-7412
# 附加（观察，不判 FAIL）：mode=hybrid 默认模式在同一文档上的 total/命中
#   —— 已知 P1（决策卡 t_9013e8b2：默认上传 pageindex 与默认检索模式错配），只记录数值。
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

KB_ID="${KB_ID:-22bcb345-8326-479c-958b-51daa2905715}"
RAW=03-testing/evidence/PI-V4_raw
TOKEN_MARK="PI-TOKEN-7412"
Q_MAIN="追溯本次巡检批次时应该用哪个口令定位日志？"
RUNS="${RUNS:-3}"
mkdir -p "$RAW"
kb_login || exit 1

echo "==== PI-09 [PI-V4] 主查询 mode=pageindex top_k=3 × ${RUNS} ===="
FAILS=0
declare -a CHECKS=()
N_EACH=0; N_ZERO=0; N_HIT=0
i=0
while [ "$i" -lt "$RUNS" ]; do
  i=$((i + 1))
  BODY="$(jq -cn --arg q "$Q_MAIN" '{query:$q, mode:"pageindex", top_k:3}')"
  kb_post "/api/v1/knowledge-bases/$KB_ID/search" "$BODY" \
    -m 180 -o "$RAW/PI-09_search_pageindex_run$i.json" > "$RAW/PI-09_search_pageindex_run$i.w"
  W="$(tr -d '\n' < "$RAW/PI-09_search_pageindex_run$i.w")"
  CODE="$(jq -r '.code // -1' "$RAW/PI-09_search_pageindex_run$i.json")"
  TOT="$(jq -r '.data.total // 0' "$RAW/PI-09_search_pageindex_run$i.json")"
  HITS="$(jq -r --arg m "$TOKEN_MARK" '[.data.items[]?.content|test($m)]|map(select(.==true))|length' "$RAW/PI-09_search_pageindex_run$i.json")"
  echo "[run$i] $W"
  echo "[run$i] $(jq -c '{code,total:.data.total,took_ms:.data.took_ms,message:(.data.message//"<none>"),error:(.data.error//"<none>"),items:[.data.items[]?|{document_id,node_title:.metadata.node_title,has_token:(.content|test("PI-TOKEN-7412"))}]}' "$RAW/PI-09_search_pageindex_run$i.json")"
  N_EACH=$((N_EACH + 1))
  if [ "$TOT" -ge 1 ]; then N_HIT=$((N_HIT + 1)); else N_ZERO=$((N_ZERO + 1)); fi
  if [ "$CODE" = "0" ] && [ "$TOT" -ge 1 ] && [ "$HITS" -ge 1 ]; then V=PASS; else V=FAIL; FAILS=$((FAILS + 1)); fi
  CHECKS+=("{\"id\":\"S1-S3-run$i\",\"desc\":\"pageindex 检索第 $i 次：code=0 且 total>=1 且含口令\",\"expected\":\"code=0,total>=1,hit>=1\",\"actual\":\"code=$CODE,total=$TOT,hit=$HITS\",\"verdict\":\"$V\"}")
  sleep 1
done
echo "[PI-09] 命中稳定性: $N_HIT/$N_EACH 次 total>=1（$N_ZERO 次 0 命中）"

echo "==== PI-09 观察项：同文档 mode=hybrid（默认模式）===="
BODY2="$(jq -cn --arg q "$Q_MAIN" '{query:$q, mode:"hybrid", top_k:3}')"
kb_post "/api/v1/knowledge-bases/$KB_ID/search" "$BODY2" \
  -m 180 -o "$RAW/PI-09_search_hybrid_obs.json" > "$RAW/PI-09_search_hybrid_obs.w"
cat "$RAW/PI-09_search_hybrid_obs.w"
echo "[obs-hybrid] $(jq -c '{code,total:.data.total,took_ms:.data.took_ms,items:[.data.items[]?|{document_id,filename,match_type}]}' "$RAW/PI-09_search_hybrid_obs.json")（已知 P1，与 t_9013e8b2 同源，不判 FAIL）"

printf '%s\n' "${CHECKS[@]}" > "$RAW/PI-09_checks.jsonl"
jq -n --arg v "$([ "$FAILS" -gt 0 ] && echo FAIL || echo PASS)" --argjson fails "$FAILS" \
      --arg kb "$KB_ID" --argjson n "$N_EACH" --argjson hit "$N_HIT" --argjson zero "$N_ZERO" \
      --slurpfile checks "$RAW/PI-09_checks.jsonl" \
      '{case:"PI-09", verdict:$v, fails:$fails, kb_id:$kb, runs:$n, runs_with_hits:$hit, runs_zero:$zero,
        checks:$checks, generated_at:"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}' > "$RAW/PI-09_result.json"
echo "==== PI-09 DONE verdict=$(jq -r .verdict "$RAW/PI-09_result.json") fails=$FAILS ===="
