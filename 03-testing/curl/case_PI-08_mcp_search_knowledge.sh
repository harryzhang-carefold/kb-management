#!/usr/bin/env bash
# =============================================================================
# 用例: PI-08  MCP search_knowledge 引用链路冒烟 —— 默认上传的 pageindex 文档能否被
#             智能助手（MCP）检索到？（卡 t_2ba41218 / VI-PI-4 / 用例6 必做项）
# 接口: POST http://127.0.0.1:9100/mcp     JSON-RPC 2.0  method=tools/call
#       tool = search_knowledge  {query, kb_id, mode, top_k}
# 入参:
#   MCP_URL 默认 http://127.0.0.1:9100/mcp
#   KEY     从 infra/.env 的 KB_MCP_API_KEY 读取（**只用于请求头，脚本不打印**）
#   KB_ID   默认 22bcb345-8326-479c-958b-51daa2905715
#           （VI-PI-4 自建 KB，含 2 篇「线上 UI 默认上传」的 pageindex 文档，chunk_count=0）
#   QUERY   默认 PI-TOKEN-7412（pi_default_doc.md 正文唯一口令）
#   MODES   默认 "hybrid vector keyword"
# 首次执行: 2026-10-12T04:01:51Z（run1：KB 内只有 2 篇默认 pageindex 文档）
# 反向对照: 2026-10-12T04:08:00Z（run2：同一 KB 再上传 1 篇显式 embedding 文档）
# 首次结果:
#   run1 hybrid/vector/keyword total = 0/0/0（0 命中）
#   run2 hybrid/vector/keyword total = 2/2/1（全部命中 9c8f8743… 即显式 embedding 文档，
#        且带 doc_url + location；两篇默认 pageindex 文档从未出现在任何一次返回里）
#   → 见 03-testing/evidence/PI-V4_case2_case6.txt / PI-V4_result.json
# 断言:
#   P1 HTTP 200 且 JSON-RPC 无 error
#   P2 工具返回体可解析（含 total/items）
#   C1 若 KB 内只有 pageindex 文档（chunk_count=0）→ 期望 total=0（记录为「冲突/BUG 证据」）
#   C2 若 KB 内已有 embedding 文档（反向对照）→ 期望 total>=1 且 items 带 doc_url
#   P3 逐项记录 match_type / document_id / doc_url / location（不判 FAIL，只留痕）
# 用法:
#   bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh
#   KB_ID=xxx MODES=hybrid bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management

MCP_URL="${MCP_URL:-http://127.0.0.1:9100/mcp}"
KB_ID="${KB_ID:-22bcb345-8326-479c-958b-51daa2905715}"
QUERY="${QUERY:-PI-TOKEN-7412}"
MODES="${MODES:-hybrid vector keyword}"
TOP_K="${TOP_K:-5}"
RUN_TAG="${RUN_TAG:-run1}"
RAW="${RAW:-03-testing/evidence/PI-V4_raw}"
mkdir -p "$RAW"

# --- key 读取（不打印）------------------------------------------------------
ENVF="infra/.env"
KEY="$(grep -E '^KB_MCP_API_KEY=' "$ENVF" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')"
if [ -z "$KEY" ]; then echo "[PI-08] FAIL: $ENVF 中无 KB_MCP_API_KEY"; exit 1; fi
echo "[PI-08] mcp=$MCP_URL kb_id=$KB_ID query=$QUERY modes=[$MODES] key_len=${#KEY}（不打印明文）"

# --- SSE/JSON 响应归一化解析 ------------------------------------------------
mcp_extract_result() { # $1=原始响应文件  → stdout: JSON-RPC 响应对象
  local f="$1"
  if jq -e '.jsonrpc' "$f" >/dev/null 2>&1; then
    cat "$f"
  else
    # text/event-stream：取最后一条 data: 行（tools/call 的结果帧）
    grep '^data: ' "$f" | sed 's/^data: //' | jq -c 'select(.id==1)' | tail -n1
  fi
}

FAILS=0
declare -a CHECKS=()
check() {
  local id="$1" desc="$2" exp="$3" act="$4"
  if [ "$exp" = "$act" ]; then
    echo "[$id] PASS  $desc  (expected=$exp actual=$act)"
    CHECKS+=("{\"id\":\"$id\",\"desc\":\"$desc\",\"expected\":\"$exp\",\"actual\":\"$act\",\"verdict\":\"PASS\"}")
  else
    echo "[$id] FAIL  $desc  (expected=$exp actual=$act)"
    CHECKS+=("{\"id\":\"$id\",\"desc\":\"$desc\",\"expected\":\"$exp\",\"actual\":\"$act\",\"verdict\":\"FAIL\"}")
    FAILS=$((FAILS + 1))
  fi
}

echo "==== PI-08 [$RUN_TAG] 逐 mode 调用 tools/call search_knowledge ===="
for MODE in $MODES; do
  BODY="$(jq -cn --arg q "$QUERY" --arg kb "$KB_ID" --arg m "$MODE" --argjson k "$TOP_K" \
    '{jsonrpc:"2.0", id:1, method:"tools/call",
      params:{name:"search_knowledge", arguments:{query:$q, kb_id:$kb, mode:$m, top_k:$k}}}')"
  OUT="$RAW/PI-08_${RUN_TAG}_${MODE}.raw"
  HDR="$RAW/PI-08_${RUN_TAG}_${MODE}.headers"
  echo "--- mode=$MODE : POST $MCP_URL (JSON-RPC tools/call) ---"
  curl -sS -N -m 120 -X POST "$MCP_URL" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H "Authorization: Bearer $KEY" \
    -H "MCP-Session-Id: pi08-${RUN_TAG}-${MODE}" \
    -d "$BODY" -o "$OUT" -D "$HDR" \
    -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s SIZE=%{size_download}\n' | sed "s/^/[mcp-$MODE] /"
  echo "[mcp-$MODE] headers: $(grep -i '^HTTP/\|^content-type' "$HDR" | tr -d '\r' | tr '\n' ' ')"
  echo "[mcp-$MODE] raw_head: $(head -c 400 "$OUT" | tr '\n' ' ')"

  RES="$(mcp_extract_result "$OUT")"
  if [ -z "$RES" ]; then
    echo "[mcp-$MODE] FAIL: 无法解析 JSON-RPC 响应"
    CHECKS+=("{\"id\":\"P1-$MODE\",\"desc\":\"JSON-RPC 响应可解析\",\"expected\":\"jsonrpc\",\"actual\":\"unparsable\",\"verdict\":\"FAIL\"}")
    FAILS=$((FAILS + 1)); continue
  fi
  ERR="$(printf '%s' "$RES" | jq -r 'has("error")|tostring')"
  check "P1-$MODE" "JSON-RPC 无 error（mode=$MODE）" "false" "$ERR"

  TEXT="$(printf '%s' "$RES" | jq -r '.result.content[0].text // empty')"
  if [ -z "$TEXT" ]; then
    echo "[mcp-$MODE] no tool text; full=$RES"
    continue
  fi
  printf '%s' "$TEXT" > "$RAW/PI-08_${RUN_TAG}_${MODE}.payload.json"
  TOTAL="$(printf '%s' "$TEXT" | jq -r '.total // "ERR"')"
  echo "[mcp-$MODE] tool-result: $(printf '%s' "$TEXT" | jq -c '{query,mode,total,took_ms,error}')"
  echo "[mcp-$MODE] items: $(printf '%s' "$TEXT" | jq -c '[.items[]?|{document_id,filename,chunk_index,match_type,score,doc_url:(.doc_url//"<absent>"),location:(.location//"<absent>"),has_token:(.content|test("PI-TOKEN-7412"))}]')"
  echo "PI08_MODE_${MODE}_TOTAL=$TOTAL"
done

echo "==== PI-08 [$RUN_TAG] 汇总 ===="
for MODE in $MODES; do
  P="$RAW/PI-08_${RUN_TAG}_${MODE}.payload.json"
  [ -f "$P" ] || continue
  echo "  $MODE: total=$(jq -r '.total // "ERR"' "$P")  docs=$(jq -c '[.items[]?.document_id]|unique' "$P")"
done

printf '%s\n' "${CHECKS[@]}" > "$RAW/PI-08_${RUN_TAG}_checks.jsonl"
jq -n --arg v "$([ "$FAILS" -gt 0 ] && echo FAIL || echo PASS)" --argjson fails "$FAILS" \
      --arg kb "$KB_ID" --arg query "$QUERY" --arg tag "$RUN_TAG" \
      --argjson totals "$( for M in $MODES; do P="$RAW/PI-08_${RUN_TAG}_${M}.payload.json"; if [ -f "$P" ]; then jq -cn --arg m "$M" --argjson t "$(jq -r '.total // -1' "$P")" '{($m):$t}'; else echo '{}'; fi; done | jq -s 'add' )" \
      --slurpfile checks "$RAW/PI-08_${RUN_TAG}_checks.jsonl" \
      '{case:"PI-08", run:$tag, verdict:$v, fails:$fails, kb_id:$kb, query:$query, totals:$totals, checks:$checks,
        generated_at:"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}' > "$RAW/PI-08_${RUN_TAG}_result.json"
echo "[PI-08] result -> $RAW/PI-08_${RUN_TAG}_result.json"
echo "==== PI-08 [$RUN_TAG] DONE ===="
