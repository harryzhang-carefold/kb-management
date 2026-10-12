#!/usr/bin/env bash
# =============================================================================
# 用例: PI-07  模拟「历史无 index_type 文档」→ 仍按 embedding 兜底，检索不受影响
# 卡:   t_bbb32bcf (VI-PI-3, 验证链第 3 段)   用例编号: 用例 5（步骤 6）
# ★★ 本脚本产出的是【模拟用例】：真实存量里"无 index_type 的文档"为 0 篇 ★★
#    证据：03-testing/evidence/PI-V3_legacy_audit.json → index_type_dist_all = {embedding:77, pageindex:34}
#    无 <none> 键；db_probe legacy 亦为 0 行。**不得**把本脚本结果当作存量真实数据分布。
#
# 目的: 在自建测试 KB 的文档上人工去掉 meta.index_type，复现历史老文档形态，验证：
#   - reindex 分流仍按 embedding 兜底（api/documents.py:289 `(doc.meta or {}).get("index_type","embedding")`）
#   - worker 分流判断同样不升级为 pageindex（workers/tasks.py:119 仅 == "pageindex" 才走树）
#   - GET /documents/{id} 在 meta 缺 index_type 时原样返回（兜底只在前端 `|| 'embedding'` 与分流决策里）
#   - 该文档检索（vector / hybrid）仍命中正文口令 LEG-TOKEN-6390
#
# 接口:
#   POST /api/v1/knowledge-bases                                    建自测 KB
#   POST /api/v1/knowledge-bases/{kb}/documents                     上传（显式 index_type=embedding）
#   GET  /api/v1/knowledge-bases/{kb}/documents/{doc}               轮询 / 原样返回核对
#   POST /api/v1/knowledge-bases/{kb}/documents/{doc}/reindex       重建索引（兜底分流判定）
#   POST /api/v1/knowledge-bases/{kb}/search                        vector / hybrid
# 写库动作（唯一一处，严格限定）: 03-testing/curl/lib/strip_index_type.py
#   —— 只删 --doc 指定文档的 meta.index_type 一个键，校验归属 KB、影响行数必须=1，含树文档直接拒绝。
#
# 入参:
#   KB 名  = 验证-兜底-legacy-VI-PI-3-<HHMMSS>（本次新建）
#   上传   = file=legacy_no_index_type_doc.md（sha256 c3257bbe446e14425a9eeeb392041434cb64983595ea41cf8f3195847880b985）
#            **显式** -F index_type=embedding（先保证有分块），随后人工删键模拟老文档
#   检索   = {"query":"LEG-TOKEN-6390","mode":"vector"|"hybrid","top_k":5}
# 首次执行: 2026-10-12T03:5x UTC（本次）
# 断言（任一 FAIL → 本用例 FAIL）:
#   C1 上传后 meta.index_type == "embedding" 且 status=indexed、chunk_count>0
#   C2 删键后 GET /documents/{id} 的 meta **不含** index_type（API 原样返回，不自动补默认值）
#   C3 POST reindex 响应 data.index_type == "embedding"（兜底分流，未被改成 pageindex）★关键
#   C4 reindex 后 status == indexed、chunk_count > 0
#   C5 search mode=vector 命中 LEG-TOKEN-6390
#   C6 search mode=hybrid 命中 LEG-TOKEN-6390
#   C7 代码复核: 前端 KbDetailView.vue 显示兜底 `|| 'embedding'` 仍在（grep 留证）
#   C8 MCP 9100 list_documents/search_knowledge 显示兜底（mcp_server.py:100）—— 调不通则记 NOT-RUN
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

STAMP="$(date -u +%H%M%S)"
KB_NAME="验证-兜底-legacy-VI-PI-3-${STAMP}"
FIXTURE="03-testing/fixtures_pi/legacy_no_index_type_doc.md"
TOKEN_MARK="LEG-TOKEN-6390"
RAW=03-testing/evidence/raw
mkdir -p "$RAW"
RESULT="$RAW/PI-07_result.json"

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

kb_login || exit 1

echo "==== PI-07 建自测 KB（模拟用例，非存量真实数据）: $KB_NAME ===="
curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL/api/v1/knowledge-bases" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KB_TOKEN" \
  -d "{\"name\":\"$KB_NAME\",\"description\":\"VI-PI-3 用例5-步骤6 模拟无 index_type 老文档\"}" \
  -o "$RAW/PI-07_kb_create.json" -w 'HTTP_CODE=%{http_code}\n'
KB_ID="$(jq -r '.data.id // empty' "$RAW/PI-07_kb_create.json")"
echo "[kb] id=$KB_ID name=$KB_NAME"
[ -n "$KB_ID" ] || { echo "[PI-07] 建库失败，终止"; exit 1; }

echo "==== PI-07 上传（显式 embedding）===="
echo "[fixture] sha256=$(sha256sum "$FIXTURE" | awk '{print $1}')"
curl -sS -m "${KB_UPLOAD_TIMEOUT:-300}" -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents" \
  -H "Authorization: Bearer $KB_TOKEN" -F "index_type=embedding" \
  -F "file=@${FIXTURE};type=text/markdown;filename=legacy_no_index_type_doc.md" \
  -o "$RAW/PI-07_upload.json" -w 'HTTP_CODE=%{http_code}\n' | tee "$RAW/PI-07_upload.w"
DOC="$(jq -r '.data.document_id // empty' "$RAW/PI-07_upload.json")"
echo "[ids] doc=$DOC"
[ -n "$DOC" ] || { echo "[PI-07] 上传无 document_id，终止"; exit 1; }

n=0; FIN=""; ST=""
while [ "$n" -lt 60 ]; do
  n=$((n + 1))
  curl -sS -m 30 "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents/$DOC" \
    -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-07_poll_$n.json" -w "HTTP_CODE=%{http_code}\n" >> "$RAW/PI-07_polls.log"
  FIN="$RAW/PI-07_poll_$n.json"; ST="$(jq -r '.data.document.status // empty' "$FIN")"
  echo "[poll $n] t=$((n * 5))s status=$ST chunk_count=$(jq -r '.data.document.chunk_count // "-"' "$FIN")"
  if [ "$ST" = "indexed" ] || [ "$ST" = "failed" ]; then break; fi
  sleep 5
done
cp -f "$FIN" "$RAW/PI-07_doc_after_upload.json"
IT0="$(jq -r '.data.document.meta.index_type // "<absent>"' "$RAW/PI-07_doc_after_upload.json")"
CC0="$(jq -r '.data.document.chunk_count // 0' "$RAW/PI-07_doc_after_upload.json")"
if [ "${CC0:-0}" -gt 0 ] 2>/dev/null; then CC0V="gt0"; else CC0V="eq0"; fi
check C1a "上传后 meta.index_type 为 embedding" "embedding" "$IT0"
check C1b "上传后 status 为 indexed" "indexed" "$ST"
check C1c "上传后 chunk_count > 0（actual=$CC0）" "gt0" "$CC0V"

echo "==== PI-07 C2: 人工删键模拟历史老文档（仅本脚本自建文档）===="
backend/.venv/bin/python 03-testing/curl/lib/strip_index_type.py --doc "$DOC" --expect-kb "$KB_ID" \
  2>&1 | tee "$RAW/PI-07_strip.log"
curl -sS -m "$KB_TIMEOUT" "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents/$DOC" \
  -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-07_doc_after_strip.json" -w 'HTTP_CODE=%{http_code}\n'
jq -c '{code,status:.data.document.status,chunk_count:.data.document.chunk_count,meta:.data.document.meta}' \
  "$RAW/PI-07_doc_after_strip.json"
HAS_IT="$(jq -r '(.data.document.meta|has("index_type"))|tostring' "$RAW/PI-07_doc_after_strip.json")"
check C2 "删键后 GET 返回的 meta 不含 index_type（原样返回）" "false" "$HAS_IT"

echo "==== PI-07 C3: POST reindex → 兜底分流应为 embedding ★关键 ===="
curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents/$DOC/reindex" \
  -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-07_reindex.json" -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-07_reindex.w"
jq -c '{code,message,data}' "$RAW/PI-07_reindex.json"
IT_RE="$(jq -r '.data.index_type // "<absent>"' "$RAW/PI-07_reindex.json")"
check C3 "reindex 响应 data.index_type 为 embedding（无 index_type 兜底）" "embedding" "$IT_RE"

echo "==== PI-07 C4: 轮询 reindex 后的文档 ===="
m=0; FIN2=""; ST2=""
while [ "$m" -lt 60 ]; do
  m=$((m + 1))
  curl -sS -m 30 "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents/$DOC" \
    -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-07_poll2_$m.json" -w "HTTP_CODE=%{http_code}\n" >> "$RAW/PI-07_polls2.log"
  FIN2="$RAW/PI-07_poll2_$m.json"; ST2="$(jq -r '.data.document.status // empty' "$FIN2")"
  echo "[poll-r $m] t=$((m * 5))s status=$ST2 chunk_count=$(jq -r '.data.document.chunk_count // "-"' "$FIN2") index_type=$(jq -r '.data.document.meta.index_type // "<absent>"' "$FIN2")"
  if [ "$ST2" = "indexed" ] || [ "$ST2" = "failed" ]; then break; fi
  sleep 5
done
cp -f "$FIN2" "$RAW/PI-07_doc_after_reindex.json"
CC2="$(jq -r '.data.document.chunk_count // 0' "$RAW/PI-07_doc_after_reindex.json")"
if [ "${CC2:-0}" -gt 0 ] 2>/dev/null; then CC2V="gt0"; else CC2V="eq0"; fi
check C4a "reindex 后 status 为 indexed" "indexed" "$ST2"
check C4b "reindex 后 chunk_count > 0（actual=$CC2）" "gt0" "$CC2V"

echo "==== PI-07 C5/C6: 检索兜底文档 ===="
for MODE in vector hybrid; do
  curl -sS -m 120 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $KB_TOKEN" \
    -d "{\"query\":\"$TOKEN_MARK\",\"mode\":\"$MODE\",\"top_k\":5}" \
    -o "$RAW/PI-07_search_${MODE}.json" -w "HTTP_CODE=%{http_code} TIME=%{time_total}s\n" | sed "s/^/[search-$MODE] /"
  TOT="$(jq -r '.data.total // 0' "$RAW/PI-07_search_${MODE}.json")"
  HIT="$(jq -r --arg m "$TOKEN_MARK" '[.data.items[]? | select((.content|test($m)) or (.filename=="legacy_no_index_type_doc.md"))] | length' "$RAW/PI-07_search_${MODE}.json")"
  echo "[search-$MODE] total=$TOT 命中=$HIT items=$(jq -c '[.data.items[]?|{filename,score,match_type,has_token:(.content|test("LEG-TOKEN-6390"))}]' "$RAW/PI-07_search_${MODE}.json")"
  if [ "${TOT:-0}" -ge 1 ] && [ "${HIT:-0}" -ge 1 ]; then V="PASS"; else V="FAIL"; FAILS=$((FAILS + 1)); fi
  CHECKS+=("{\"id\":\"$( [ "$MODE" = vector ] && echo C5 || echo C6 )\",\"desc\":\"search mode=$MODE 命中兜底文档口令\",\"expected\":\"total>=1 && 命中>=1\",\"actual\":\"total=$TOT hit=$HIT\",\"verdict\":\"$V\"}")
  echo "[$([ "$MODE" = vector ] && echo C5 || echo C6)] $V  search mode=$MODE (total=$TOT hit=$HIT)"
done

echo "==== PI-07 C7: 前端代码复核（显示兜底 || 'embedding'）===="
VUE=frontend/src/views/KbDetailView.vue
grep -n "index_type || 'embedding'\|meta?.index_type || 'embedding'\|index_type || \"embedding\"\|const it = row.meta?.index_type || 'embedding'" "$VUE" \
  | tee "$RAW/PI-07_vue_grep.txt"
VUE_HITS="$(grep -c "index_type || 'embedding'" "$VUE")"
echo "[vue] 命中行数=$VUE_HITS（KbDetailView.vue:61/62 列表标签 + :273 重建索引分流）"
if [ "${VUE_HITS:-0}" -ge 2 ]; then V="PASS"; else V="FAIL"; FAILS=$((FAILS + 1)); fi
CHECKS+=("{\"id\":\"C7\",\"desc\":\"前端显示/分流兜底 || 'embedding' 仍在\",\"expected\":\">=2\",\"actual\":\"$VUE_HITS\",\"verdict\":\"$V\"}")
echo "[C7] $V  前端兜底 grep 命中 $VUE_HITS 处"

echo "==== PI-07 C8: MCP 9100 兜底复核（尽力而为，调不通记 NOT-RUN）===="
MCP_FILE="$RAW/PI-07_mcp_attempt.txt"
: > "$MCP_FILE"
{
  echo '# MCP 兜底复核尝试：mcp_server.py:100 的 (d.meta or {}).get("index_type","embedding")'
  echo "# 时间: $(date -u +%Y-%m-%dT%H:%M:%SZ)  target: http://127.0.0.1:9100"
  echo "# 说明: tools/call 完整调用序列与 case_PI-08 归第 4 段（t_2ba41218）；本段只做最小可达性探测。"
  curl -sS -m 8 -o /dev/null -w 'GET / -> HTTP_CODE=%{http_code}\n' http://127.0.0.1:9100/ 2>&1 || echo "GET / 失败"
} >> "$MCP_FILE" 2>&1
cat "$MCP_FILE"
echo "[C8] NOT-RUN（MCP tools/call 最小调用序列归第 4 段 t_2ba41218；本段以代码复核为准）"
CHECKS+=("{\"id\":\"C8\",\"desc\":\"MCP 9100 list_documents 显示兜底\",\"expected\":\"-\",\"actual\":\"NOT-RUN（归第4段）\",\"verdict\":\"NOT-RUN\"}")

VERDICT="PASS"; [ "$FAILS" -gt 0 ] && VERDICT="FAIL"
printf '%s\n' "${CHECKS[@]}" > "$RAW/PI-07_checks.jsonl"
jq -n --arg v "$VERDICT" --argjson fails "$FAILS" --arg kb "$KB_ID" --arg kbn "$KB_NAME" \
      --arg doc "$DOC" --argjson vue "$VUE_HITS" \
      --slurpfile checks "$RAW/PI-07_checks.jsonl" \
      '{case:"PI-07", simulated:true,
        simulated_note:"模拟用例：真实存量为 0 篇无 index_type 文档（见 PI-V3_legacy_audit.json），本卡为人工删键复现",
        verdict:$v, fails:$fails, kb_id:$kb, kb_name:$kbn, doc_id:$doc, vue_fallback_hits:$vue,
        checks:$checks, generated_at:"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}' > "$RESULT"
echo "==== PI-07 DONE  verdict=$VERDICT fails=$FAILS  kb=$KB_ID doc=$DOC ===="
echo "[summary] $RESULT"
exit 0
