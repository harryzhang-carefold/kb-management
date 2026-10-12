#!/usr/bin/env bash
# =============================================================================
# 复测/稳定性重放脚本（PI-02 主查询 + PI-03 主问答）
# 说明：这不是新的用例命令——是按 SOUL「复测=重放旧命令」原则，重放
#       03-testing/curl/case_PI-02_search_pageindex.sh 的主查询 body
#       与 case_PI-03_chat_pageindex.sh 的主问答 body（入参完全一致，未改一字）。
# 目的：首执 PI-02 主查询 total=0（而同样问法的 chat 命中 sources=1），
#       需判定是「确定性 0 命中」还是「LLM 选节点非确定性」，故多跑几轮留证。
# 时间: 2026-10-12T03:3x UTC
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh
KB_ID="${KB_ID:-32b1101f-efd6-467c-900a-255c75656791}"
RAW=03-testing/evidence/raw
kb_login || exit 1

echo "==== 重放 PI-02 主查询 body × 4 ===="
for i in 1 2 3 4; do
  curl -sS -m 120 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KB_TOKEN" \
    -d '{"query":"追溯本次巡检批次时应该用哪个口令定位日志？","mode":"pageindex","top_k":3}' \
    -o "$RAW/PI-02_replay_main_$i.json" \
    -w "HTTP_CODE=%{http_code} TIME=%{time_total}s\n" | sed "s/^/[replay$i] /"
  jq -c --argjson i "$i" '{run:$i,total:.data.total,took_ms:.data.took_ms,
    hits:([.data.items[]?|select(.content|test("PI-TOKEN-7412"))]|length),
    titles:[.data.items[]?.metadata.node_title]}' "$RAW/PI-02_replay_main_$i.json"
done

echo "==== 重放 PI-03 主问答（retrieval_mode=pageindex）body × 2，只看 sources 数 ===="
for i in 1 2; do
  curl -sS -N -m 180 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/chat" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KB_TOKEN" \
    -d '{"question":"追溯本次巡检批次时应该用哪个口令定位日志？","retrieval_mode":"pageindex","top_n":3}' \
    -o "$RAW/PI-03_replay_chat_$i.sse" \
    -w "HTTP_CODE=%{http_code} TIME=%{time_total}s\n" | sed "s/^/[chat-replay$i] /"
  echo "[chat-replay$i] sources=$(grep -A1 '^event: sources' "$RAW/PI-03_replay_chat_$i.sse" | grep '^data:' | sed 's/^data: //')"
done
echo "==== 重放 DONE ===="
