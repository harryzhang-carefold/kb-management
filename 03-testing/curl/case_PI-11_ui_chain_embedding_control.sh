#!/usr/bin/env bash
# =============================================================================
# 用例: PI-11  [PI-V4] 反向对照：同一 KB 内再上传一份**显式 embedding**文档
# 卡:   t_2ba41218 (VI-PI-4)   对应任务步骤 B8（证明 PI-08 脚本本身有效）
# 接口:
#   POST /api/v1/knowledge-bases/{kb_id}/documents   multipart（显式 -F index_type=embedding）
#   GET  /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}   轮询
# 入参:
#   KB_ID   默认 22bcb345-8326-479c-958b-51daa2905715（同上，含 2 篇默认 pageindex 文档）
#   file    = pi_default_doc.md（sha256 11321dc6870f37b6f4ab895937ee4074af6db19a2db607cccb729cd1a809a0a7，
#             与 PI-08/PI-09 用的是**同一份夹具**、同一口令 PI-TOKEN-7412）
#   index_type = embedding（**显式**）
# 鉴权: 走 lib/kb_common.sh 的 kb_multipart_post / kb_get
# 首次执行: 2026-10-12T04:07:51Z
# 首次结果: code=0，doc=9c8f8743-5409-413b-87af-567fab0cb7e0，status=indexed，chunk_count=2，无 pageindex_tree
# 断言: E1 上传 code=0；E2 meta.index_type=embedding；E3 status=indexed 且 chunk_count>0
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

KB_ID="${KB_ID:-22bcb345-8326-479c-958b-51daa2905715}"
FIXTURE="03-testing/fixtures_pi/pi_default_doc.md"
RAW=03-testing/evidence/PI-V4_raw
mkdir -p "$RAW"
kb_login || exit 1

echo "==== PI-11 反向对照：显式 index_type=embedding 上传 ===="
echo "[req-form] file=@$FIXTURE ; index_type=embedding（显式）"
echo "[fixture] sha256=$(sha256sum "$FIXTURE" | awk '{print $1}')"
kb_multipart_post "/api/v1/knowledge-bases/$KB_ID/documents" \
  -F "index_type=embedding" \
  -F "file=@${FIXTURE};type=text/markdown;filename=pi_default_doc_embedding.md" \
  -o "$RAW/PI-11_upload_emb.json" > "$RAW/PI-11_upload_emb.w"
cat "$RAW/PI-11_upload_emb.w"
echo "[upload] $(jq -c '{code,message,data}' "$RAW/PI-11_upload_emb.json")"
DOC="$(jq -r '.data.document_id // empty' "$RAW/PI-11_upload_emb.json")"
echo "[ids] doc_embedding=$DOC"
[ -n "$DOC" ] || { echo "[PI-11] FAIL: 无 document_id"; exit 1; }

i=0; FINAL=""
while [ "$i" -lt 60 ]; do
  i=$((i + 1))
  kb_get "/api/v1/knowledge-bases/$KB_ID/documents/$DOC" \
    -m 60 -o "$RAW/PI-11_doc_poll.json" >> "$RAW/PI-11_polls.log"
  FINAL="$RAW/PI-11_doc_poll.json"
  S="$(jq -r '.data.document.status // "-"' "$FINAL")"
  echo "[poll $i] t=$((i * 4))s status=$S index_type=$(jq -r '.data.document.meta.index_type // "-"' "$FINAL") chunk_count=$(jq -r '.data.document.chunk_count // "-"' "$FINAL")"
  if [ "$S" = "indexed" ] || [ "$S" = "failed" ]; then break; fi
  sleep 4
done
cp -f "$FINAL" "$RAW/PI-11_doc_final.json"
jq -c '{code, status:.data.document.status, chunk_count:.data.document.chunk_count,
        index_type:(.data.document.meta.index_type // "<absent>"),
        has_tree:(.data.document.meta|has("pageindex_tree"))}' "$RAW/PI-11_doc_final.json"
echo "PI11_DOC_EMBEDDING=$DOC"
echo "==== PI-11 DONE ===="
