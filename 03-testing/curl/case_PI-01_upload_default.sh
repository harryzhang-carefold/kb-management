#!/usr/bin/env bash
# =============================================================================
# 用例: PI-01  默认上传（不传 index_type）应落 pageindex 且非降级
# 卡:   t_32351222 (VI-PI-2, 验证链第 2 段)
# 接口: POST /api/v1/knowledge-bases/{kb_id}/documents   (multipart/form-data)
#       GET  /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}   (轮询)
#       GET  /openapi.json                     (契约对照)
# 入参: file=pi_default_doc.md (sha256 11321dc6870f37b6f4ab895937ee4074af6db19a2db607cccb729cd1a809a0a7)
#       **请求中绝不出现 index_type 字段**（只有 -F "file=@..."，无 -F index_type=...）
#       KB_ID 默认取自建库 32b1101f-efd6-467c-900a-255c75656791（可用 KB_ID 覆盖）
# 首次执行: 2026-10-12T03:30:xx UTC
# 首次结果: 见 03-testing/evidence/PI-V2_case1_case3.txt
# 断言(任一不满足=本用例 FAIL):
#   A1 上传 HTTP 200 且 code=0，返回 document_id/task_id
#   A2 meta.index_type == "pageindex"
#   A3 meta.pageindex_status == "ok"（degraded/failed 判 FAIL）
#   A4 pageindex_tree.status=="ok"、tree.model=="deepseek-flash"、node_count>=2、build_ms>0
#   A5 tree.root 为 dict 且含 node_id/title/children，0<=start<end<=full_text_chars
#   A6 反降级旁证: tree.root.title != 夹具 markdown 标题
#   A7 doc.status == "indexed"; 记录 chunk_count
#   A8 契约对照: openapi upload index_type default == "pageindex"
# 末尾 -w 打印 HTTP_CODE/TIME。
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

KB_ID="${KB_ID:-32b1101f-efd6-467c-900a-255c75656791}"
FIXTURE="${FIXTURE:-03-testing/fixtures_pi/pi_default_doc.md}"
EVID=03-testing/evidence
RAW="$EVID/raw"

kb_login || exit 1
mkdir -p "$RAW"

echo "==== PI-01 上传（不传 index_type）===="
echo "[req-form] file=@${FIXTURE}  ; index_type 字段: 未传（无 -F index_type=...）"
echo "[req-form] 完整字段名清单: file"
echo "[fixture] sha256=$(sha256sum "$FIXTURE" | awk '{print $1}')"

curl -sS -m 120 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -F "file=@${FIXTURE};type=text/markdown;filename=pi_default_doc.md" \
  -o "$RAW/PI-01_upload.json" \
  -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-01_upload.w"

echo "[upload-raw] $(cat "$RAW/PI-01_upload.json")"

DOC_ID="$(jq -r '.data.document_id // empty' "$RAW/PI-01_upload.json")"
TASK_ID="$(jq -r '.data.task_id // empty' "$RAW/PI-01_upload.json")"
echo "[ids] document_id=$DOC_ID task_id=$TASK_ID"

if [ -z "$DOC_ID" ]; then
  echo "[PI-01] 无 document_id，终止轮询"
  exit 1
fi

echo "==== PI-01 轮询 GET /documents/{id}（间隔 5s，上限 400s）===="
POLL_LOG="$RAW/PI-01_polls.log"
: > "$POLL_LOG"
i=0
STATUS=""
FINAL=""
while [ "$i" -lt 80 ]; do
  i=$((i + 1))
  curl -sS -m 30 "$BASE_URL/api/v1/knowledge-bases/$KB_ID/documents/$DOC_ID" \
    -H "Authorization: Bearer $KB_TOKEN" \
    -o "$RAW/PI-01_doc_poll_$i.json" \
    -w "HTTP_CODE=%{http_code} TIME=%{time_total}s\n" >> "$POLL_LOG"
  FINAL="$RAW/PI-01_doc_poll_$i.json"
  STATUS="$(jq -r '.data.document.status // empty' "$FINAL")"
  PIS="$(jq -r '.data.document.meta.pageindex_status // empty' "$FINAL")"
  echo "[poll $i] t=$((i * 5))s status=$STATUS pageindex_status=$PIS"
  if [ "$STATUS" = "indexed" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  sleep 5
done

cp -f "$FINAL" "$RAW/PI-01_doc_final.json"

echo "==== PI-01 关键字段 ===="
jq -c '{code, status:.data.document.status, chunk_count:.data.document.chunk_count,
        index_type:.data.document.meta.index_type,
        pageindex_status:.data.document.meta.pageindex_status,
        tree_status:.data.document.meta.pageindex_tree.status,
        tree_model:.data.document.meta.pageindex_tree.model,
        node_count:.data.document.meta.pageindex_tree.node_count,
        build_ms:.data.document.meta.pageindex_tree.build_ms,
        full_text_chars:.data.document.meta.pageindex_tree.full_text_chars,
        root_title:.data.document.meta.pageindex_tree.root.title,
        root_node_id:.data.document.meta.pageindex_tree.root.node_id,
        root_children_len:(.data.document.meta.pageindex_tree.root.children|length),
        root_start:.data.document.meta.pageindex_tree.root.start,
        root_end:.data.document.meta.pageindex_tree.root.end
       }' "$RAW/PI-01_doc_final.json"

echo "==== PI-01 契约对照 openapi.json ===="
curl -sS -m 20 "$BASE_URL/openapi.json" -o "$RAW/openapi_pi_v2.json" -w 'HTTP_CODE=%{http_code}\n'
jq -r '.components.schemas.Body_upload_doc_api_v1_knowledge_bases__kb_id__documents_post.properties.index_type.default' \
  "$RAW/openapi_pi_v2.json" | sed 's/^/[openapi] upload index_type default=/'

echo "==== PI-01 DONE (doc_id=$DOC_ID) ===="
