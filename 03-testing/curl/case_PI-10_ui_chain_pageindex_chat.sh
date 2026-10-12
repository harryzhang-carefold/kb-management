#!/usr/bin/env bash
# =============================================================================
# 用例: PI-10  [PI-V4] 线上 UI 默认上传的 pageindex 文档——pageindex 模式问答 sources
# 卡:   t_2ba41218 (VI-PI-4)   对应任务步骤 A5 第 2 半
# 接口: POST /api/v1/knowledge-bases/{kb_id}/chat   (SSE, text/event-stream)
# 入参(主): {"question":"追溯本次巡检批次时应该用哪个口令定位日志？","retrieval_mode":"pageindex","top_n":3}
#       KB_ID 默认 22bcb345-8326-479c-958b-51daa2905715
# 鉴权: 走 lib/kb_common.sh 的 kb_post（token 由 kb_login 注入）
# 说明: 命令形状与第 2 段 case_PI-03_chat_pageindex.sh 一致，仅 KB_ID 不同（另存以免覆盖第 2 段 raw）。
#       主查询重复 3 次：检索侧已证实 pageindex 选节点会间歇性空结果（PI-V4_raw/DIAG3_console.txt），
#       问答侧一并按「任一 run sources=0 即 FAIL」口径跑，避免单次侥幸判 PASS。
# 首次执行: 2026-10-12T04:07:06~04:07:45Z
# 首次结果: 3 次 sources = 0 / 2 / 0 → 1/3 命中（不稳定）；默认模式观察项 sources=2（走 pageindex leg）
# 断言（任一不满足=FAIL）:
#   B1 每次 HTTP 200 且事件序列含 sources（且有 token 事件）
#   B2 每次 sources >= 1
#   B3 答案非空
# 附加（观察，不判 FAIL）：不传 retrieval_mode（走默认）时的 sources 数
#   —— 已知 P1（决策卡 t_9013e8b2），本段只记录数值。
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

KB_ID="${KB_ID:-22bcb345-8326-479c-958b-51daa2905715}"
RAW=03-testing/evidence/PI-V4_raw
Q="追溯本次巡检批次时应该用哪个口令定位日志？"
RUNS="${RUNS:-3}"
mkdir -p "$RAW"
kb_login || exit 1

FAILS=0
declare -a CHECKS=()
N_EACH=0; N_ZERO=0; N_HIT=0

sse_sources() { grep -A1 '^event: sources' "$1" | grep '^data:' | sed 's/^data: //'; }
sse_answer()  { grep -A1 '^event: token' "$1" | grep '^data:' | sed 's/^data: //' | jq -r '.token' 2>/dev/null | tr -d '\n'; }

echo "==== PI-10 [PI-V4] 主查询 retrieval_mode=pageindex top_n=3 (SSE) × ${RUNS} ===="
i=0
while [ "$i" -lt "$RUNS" ]; do
  i=$((i + 1))
  SSE="$RAW/PI-10_chat_pageindex_run$i.sse"
  HDR="$RAW/PI-10_chat_pageindex_run$i.headers"
  BODY="$(jq -cn --arg q "$Q" '{question:$q, retrieval_mode:"pageindex", top_n:3}')"
  kb_post "/api/v1/knowledge-bases/$KB_ID/chat" "$BODY" \
    -N -m 240 -o "$SSE" -D "$HDR" > "$RAW/PI-10_chat_pageindex_run$i.w"
  echo "[run$i] $(tr -d '\n' < "$RAW/PI-10_chat_pageindex_run$i.w")"
  echo "[run$i][headers] $(grep -i '^HTTP/\|^content-type' "$HDR" | tr -d '\r' | tr '\n' ' ')"
  echo "[run$i][event-counts] $(grep '^event:' "$SSE" | awk '{print $2}' | sort | uniq -c | tr '\n' ' ')"
  SRC="$(sse_sources "$SSE")"
  echo "[run$i][sources] $SRC"
  ANS="$(sse_answer "$SSE")"
  echo "[run$i][answer] $(printf '%s' "$ANS" | head -c 300)"
  echo "[run$i][error-event] $(grep -A1 '^event: error' "$SSE" | grep '^data:' | sed 's/^data: //')"
  NS="$(printf '%s' "$SRC" | jq -r '.sources|length' 2>/dev/null)"
  [ -n "${NS:-}" ] || NS=0
  N_EACH=$((N_EACH + 1))
  if [ "$NS" -ge 1 ]; then N_HIT=$((N_HIT + 1)); else N_ZERO=$((N_ZERO + 1)); fi
  if [ "$NS" -ge 1 ] && [ -n "$ANS" ]; then V=PASS; else V=FAIL; FAILS=$((FAILS + 1)); fi
  CHECKS+=("{\"id\":\"B1-B3-run$i\",\"desc\":\"pageindex 问答第 $i 次：sources>=1 且答案非空\",\"expected\":\"sources>=1,answer非空\",\"actual\":\"sources=$NS,answer_len=${#ANS}\",\"verdict\":\"$V\"}")
  sleep 1
done
echo "[PI-10] sources 稳定性: $N_HIT/$N_EACH 次 sources>=1（$N_ZERO 次 0 来源）"

echo "==== PI-10 观察项：不传 retrieval_mode（走默认模式）===="
BODY2="$(jq -cn --arg q "$Q" '{question:$q, top_n:3}')"
kb_post "/api/v1/knowledge-bases/$KB_ID/chat" "$BODY2" \
  -N -m 240 -o "$RAW/PI-10_chat_defaultmode.sse" -D "$RAW/PI-10_chat_defaultmode.headers" \
  > "$RAW/PI-10_chat_defaultmode.w"
cat "$RAW/PI-10_chat_defaultmode.w"
echo "[obs-meta] $(grep -A1 '^event: meta' "$RAW/PI-10_chat_defaultmode.sse" | grep '^data:' | sed 's/^data: //')"
echo "[obs-sources] $(sse_sources "$RAW/PI-10_chat_defaultmode.sse")"
NOBS="$(sse_sources "$RAW/PI-10_chat_defaultmode.sse" | jq -r '.sources|length' 2>/dev/null)"
[ -n "${NOBS:-}" ] || NOBS=0
echo "[PI-10-obs] 默认模式 sources=$NOBS（已知 P1，与 t_9013e8b2 同源，不判 FAIL）"

printf '%s\n' "${CHECKS[@]}" > "$RAW/PI-10_checks.jsonl"
jq -n --arg v "$([ "$FAILS" -gt 0 ] && echo FAIL || echo PASS)" --argjson fails "$FAILS" \
      --arg kb "$KB_ID" --argjson n "$N_EACH" --argjson hit "$N_HIT" --argjson zero "$N_ZERO" \
      --slurpfile checks "$RAW/PI-10_checks.jsonl" \
      '{case:"PI-10", verdict:$v, fails:$fails, kb_id:$kb, runs:$n, runs_with_sources:$hit, runs_zero_sources:$zero,
        checks:$checks, generated_at:"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}' > "$RAW/PI-10_result.json"
echo "==== PI-10 DONE verdict=$(jq -r .verdict "$RAW/PI-10_result.json") fails=$FAILS ===="
