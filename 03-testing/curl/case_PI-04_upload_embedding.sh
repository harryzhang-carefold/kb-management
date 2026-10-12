#!/usr/bin/env bash
# =============================================================================
# 用例: PI-04  显式 index_type=embedding 上传 → 分块 + 向量索引仍正常（回归）
# 卡:   t_bbb32bcf (VI-PI-3, 验证链第 3 段)   用例编号: 用例 4
# 接口:
#   POST /api/v1/knowledge-bases                                    建自测 KB
#   POST /api/v1/knowledge-bases/{kb_id}/documents                  multipart 上传
#   GET  /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}         轮询
#   POST /api/v1/knowledge-bases/{kb_id}/search                     vector / hybrid 检索
# 入参:
#   KB 名   = 验证-回归-embedding-VI-PI-3-<HHMMSS>（每次执行新建，属自建 KB）
#   上传 1  = file=emb_regression_doc.md（sha256 ad8bc0fb9722bba8611bdd98c211912420278abaccb1136fe72c0aa790dbf51d）
#             **显式** -F index_type=embedding
#   上传 2  = 同一份文档，**显式** -F index_type=pageindex（对照：证明"显式=默认"，不是唯一路径）
#   检索    = {"query":"EMB-TOKEN-8251", "mode":"vector"|"hybrid", "top_k":5}
# 首次执行: 2026-10-12T03:4x UTC（本次）
# 首次结果: 见 03-testing/evidence/PI-V3_case4_case5.txt / PI-V3_result.json
# 断言（任一 FAIL → 本用例 FAIL）:
#   A1 上传 HTTP 200 且 code=0，返回 document_id/task_id
#   A2 meta.index_type == "embedding"
#   A3 doc.status == "indexed" 且 chunk_count > 0
#   A4 meta 无 pageindex_tree 且 pageindex_status 不存在或 != "ok"  → 证明没走建树
#   A5 search mode=vector total>=1 且命中该文件（content 含 EMB-TOKEN-8251 或 filename 同名）
#   A6 search mode=hybrid 同样命中
#   A7 对照：显式 index_type=pageindex 上传同一文档 → index_type=pageindex 且最终 pageindex_status=ok
# 说明: 端点/账号全部走 lib/kb_common.sh 的环境变量，不硬编码；token 只回显长度。
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

STAMP="$(date -u +%H%M%S)"
KB_NAME="验证-回归-embedding-VI-PI-3-${STAMP}"
FIXTURE="03-testing/fixtures_pi/emb_regression_doc.md"
TOKEN_MARK="EMB-TOKEN-8251"
EVID=03-testing/evidence
RAW="$EVID/raw"
mkdir -p "$RAW"

RESULT="$RAW/PI-04_result.json"
FAILS=0
declare -a CHECKS=()
check() { # check <id> <desc> <expected> <actual>
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

echo "==== PI-04 建自测 KB: $KB_NAME ===="
curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL/api/v1/knowledge-bases" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KB_TOKEN" \
  -d "{\"name\":\"$KB_NAME\",\"description\":\"VI-PI-3 用例4 embedding 回归 + 显式对照\"}" \
  -o "$RAW/PI-04_kb_create.json" \
  -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n'
KB_ID="$(jq -r '.data.id // empty' "$RAW/PI-04_kb_create.json")"
echo "[kb] id=$KB_ID name=$KB_NAME"
if [ -z "$KB_ID" ]; then echo "[PI-04] 建库失败，终止"; exit 1; fi
export KB_ID

echo "==== PI-04 上传 1：显式 index_type=embedding ===="
echo "[req-form] file=@$FIXTURE ; index_type=embedding（显式）"
echo "[fixture] sha256=$(sha256sum "$FIXTURE" | awk '{print $1}')"
curl -sS -m "${KB_UPLOAD_TIMEOUT:-300}" -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -F "index_type=embedding" \
  -F "file=@${FIXTURE};type=text/markdown;filename=emb_regression_doc.md" \
  -o "$RAW/PI-04_upload_emb.json" \
  -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-04_upload_emb.w"
echo "[upload-emb] $(jq -c '{code,message,data}' "$RAW/PI-04_upload_emb.json")"
DOC_EMB="$(jq -r '.data.document_id // empty' "$RAW/PI-04_upload_emb.json")"
TASK_EMB="$(jq -r '.data.task_id // empty' "$RAW/PI-04_upload_emb.json")"
echo "[ids] doc_emb=$DOC_EMB task=$TASK_EMB"
[ -n "$DOC_EMB" ] || { echo "[PI-04] 上传 1 无 document_id，终止"; exit 1; }

check A1 "上传 1 HTTP/业务码" "0" "$(jq -r '.code // -1' "$RAW/PI-04_upload_emb.json")"

echo "==== PI-04 轮询 doc_emb（间隔 5s，上限 300s）===="
i=0; FINAL=""; STATUS=""
while [ "$i" -lt 60 ]; do
  i=$((i + 1))
  curl -sS -m 30 "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents/$DOC_EMB" \
    -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-04_emb_poll_$i.json" \
    -w "HTTP_CODE=%{http_code}\n" >> "$RAW/PI-04_emb_polls.log"
  FINAL="$RAW/PI-04_emb_poll_$i.json"
  STATUS="$(jq -r '.data.document.status // empty' "$FINAL")"
  echo "[poll $i] t=$((i * 5))s status=$STATUS index_type=$(jq -r '.data.document.meta.index_type // "-"' "$FINAL")"
  if [ "$STATUS" = "indexed" ] || [ "$STATUS" = "failed" ]; then break; fi
  sleep 5
done
cp -f "$FINAL" "$RAW/PI-04_emb_doc_final.json"

jq -c '{code, status:.data.document.status, chunk_count:.data.document.chunk_count,
        index_type:.data.document.meta.index_type,
        pageindex_status:(.data.document.meta.pageindex_status // "<absent>"),
        has_tree:(.data.document.meta|has("pageindex_tree")),
        meta_keys:(.data.document.meta|keys)}' "$RAW/PI-04_emb_doc_final.json"

IT="$(jq -r '.data.document.meta.index_type // "<absent>"' "$RAW/PI-04_emb_doc_final.json")"
ST="$(jq -r '.data.document.status // "<absent>"' "$RAW/PI-04_emb_doc_final.json")"
CC="$(jq -r '.data.document.chunk_count // 0' "$RAW/PI-04_emb_doc_final.json")"
HAS_TREE="$(jq -r '(.data.document.meta|has("pageindex_tree"))|tostring' "$RAW/PI-04_emb_doc_final.json")"
PIS="$(jq -r '.data.document.meta.pageindex_status // "<absent>"' "$RAW/PI-04_emb_doc_final.json")"

check A2 "meta.index_type 为 embedding" "embedding" "$IT"
check A3a "doc.status 为 indexed" "indexed" "$ST"
if [ "${CC:-0}" -gt 0 ] 2>/dev/null; then CCV="gt0"; else CCV="eq0"; fi
check A3b "chunk_count > 0（actual=$CC）" "gt0" "$CCV"
check A4a "meta 不含 pageindex_tree" "false" "$HAS_TREE"
if [ "$PIS" = "ok" ]; then PISV="ok"; else PISV="notok"; fi
check A4b "pageindex_status 不存在或 != ok（actual=$PIS）" "notok" "$PISV"

echo "==== PI-04 检索 A5/A6：vector + hybrid ===="
for MODE in vector hybrid; do
  curl -sS -m 120 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $KB_TOKEN" \
    -d "{\"query\":\"$TOKEN_MARK\",\"mode\":\"$MODE\",\"top_k\":5}" \
    -o "$RAW/PI-04_search_${MODE}.json" \
    -w "HTTP_CODE=%{http_code} TIME=%{time_total}s\n" | sed "s/^/[search-$MODE] /"
  TOT="$(jq -r '.data.total // 0' "$RAW/PI-04_search_${MODE}.json")"
  HITS="$(jq -r --arg m "$TOKEN_MARK" '[.data.items[]? | select((.content|test($m)) or (.filename=="emb_regression_doc.md"))] | length' "$RAW/PI-04_search_${MODE}.json")"
  echo "[search-$MODE] total=$TOT 命中条目=$HITS items=$(jq -c '[.data.items[]?|{filename,score,match_type,has_token:(.content|test("EMB-TOKEN-8251"))}]' "$RAW/PI-04_search_${MODE}.json")"
  if [ "${TOT:-0}" -ge 1 ] && [ "${HITS:-0}" -ge 1 ]; then V="PASS"; else V="FAIL"; FAILS=$((FAILS + 1)); fi
  CHECKS+=("{\"id\":\"$( [ "$MODE" = vector ] && echo A5 || echo A6 )\",\"desc\":\"search mode=$MODE 命中该文件\",\"expected\":\"total>=1 && 命中>=1\",\"actual\":\"total=$TOT hit=$HITS\",\"verdict\":\"$V\"}")
  echo "[$([ "$MODE" = vector ] && echo A5 || echo A6)] $V  search mode=$MODE (total=$TOT hit=$HITS)"
done

echo "==== PI-04 对照 A7：同一 KB 显式 index_type=pageindex 上传同一文档 ===="
curl -sS -m "${KB_UPLOAD_TIMEOUT:-300}" -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -F "index_type=pageindex" \
  -F "file=@${FIXTURE};type=text/markdown;filename=emb_regression_doc_pageindex.md" \
  -o "$RAW/PI-04_upload_pi.json" \
  -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-04_upload_pi.w"
DOC_PI="$(jq -r '.data.document_id // empty' "$RAW/PI-04_upload_pi.json")"
echo "[ids] doc_pi=$DOC_PI"
if [ -n "$DOC_PI" ]; then
  j=0; FINALP=""; STARTP=""
  while [ "$j" -lt 80 ]; do
    j=$((j + 1))
    curl -sS -m 30 "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents/$DOC_PI" \
      -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-04_pi_poll_$j.json" \
      -w "HTTP_CODE=%{http_code}\n" >> "$RAW/PI-04_pi_polls.log"
    FINALP="$RAW/PI-04_pi_poll_$j.json"
    STARTP="$(jq -r '.data.document.meta.pageindex_status // empty' "$FINALP")"
    echo "[poll-pi $j] t=$((j * 5))s status=$(jq -r '.data.document.status // "-"' "$FINALP") pageindex_status=$STARTP"
    if [ "$STARTP" = "ok" ] || [ "$STARTP" = "failed" ] || [ "$STARTP" = "degraded" ]; then break; fi
    sleep 5
  done
  cp -f "$FINALP" "$RAW/PI-04_pi_doc_final.json"
  jq -c '{code, status:.data.document.status, chunk_count:.data.document.chunk_count,
          index_type:.data.document.meta.index_type,
          pageindex_status:.data.document.meta.pageindex_status,
          has_tree:(.data.document.meta|has("pageindex_tree")),
          node_count:.data.document.meta.pageindex_tree.node_count}' "$RAW/PI-04_pi_doc_final.json"
  ITP="$(jq -r '.data.document.meta.index_type // "<absent>"' "$RAW/PI-04_pi_doc_final.json")"
  PISP="$(jq -r '.data.document.meta.pageindex_status // "<absent>"' "$RAW/PI-04_pi_doc_final.json")"
  check A7a "对照文档 meta.index_type 为 pageindex" "pageindex" "$ITP"
  check A7b "对照文档 pageindex_status 为 ok" "ok" "$PISP"
fi

VERDICT="PASS"; [ "$FAILS" -gt 0 ] && VERDICT="FAIL"
printf '%s\n' "${CHECKS[@]}" > "$RAW/PI-04_checks.jsonl"
jq -n --arg v "$VERDICT" --arg kb "$KB_ID" --arg kbn "$KB_NAME" \
      --arg d1 "$DOC_EMB" --arg d2 "${DOC_PI:-}" --argjson fails "$FAILS" \
      --slurpfile checks "$RAW/PI-04_checks.jsonl" \
      '{case:"PI-04", verdict:$v, fails:$fails, kb_id:$kb, kb_name:$kbn,
        doc_embedding:$d1, doc_pageindex_control:$d2,
        checks:$checks, generated_at:"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}' \
   > "$RESULT"
echo "==== PI-04 DONE  verdict=$VERDICT fails=$FAILS  kb=$KB_ID ===="
echo "[summary] $RESULT"
exit 0
