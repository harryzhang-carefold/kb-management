#!/usr/bin/env bash
# =============================================================================
# 用例: PI-06  存量真实文档行为核对（用例 5 第 1/2 半）
# 卡:   t_bbb32bcf (VI-PI-3, 验证链第 3 段)   用例编号: 用例 5（步骤 5）
# 目的: 用**真实存量文档**证明改动的兜底分支未被污染：
#       - 存量 index_type=embedding 的文档 reindex → 仍走 embedding 路径（documents.py:289 兜底）
#       - 该文档再调 pageindex/rebuild → HTTP 400「不是 PageIndex 索引方式」（互斥未被破坏）
#       - 重建后 meta.index_type 未被改写、chunk_count 仍 >0、向量检索仍命中
#       - 存量 index_type=pageindex 的文档 reindex → 仍走 pageindex 路径且建树最终 ok
#
# 选用样本（历史测试 KB，非业务 KB；只读审计结论见 evidence/PI-V3_legacy_audit.json）:
#   [S-EMB] KB=f380d232-9551-4bee-ad30-7a55606cab21 (E2E测试库)
#           doc=99c37b1e-7183-4b1b-902d-e22c9070db82 (test.txt, embedding, 1 chunk, 上传 2026-10-12T03:12:53Z < 03:16:05Z)
#           选用理由: 历史测试 KB、内部一致(chunk_count==chunk_rows==1)、改动前上传、单分块文档副作用最小
#   [S-PI ] KB=21f3f148-a8b2-404f-9412-7561ac5d6714 (UI默认pageindex验证-031125)
#           doc=7b678d3f-1ccf-4883-93d9-549cd932ec19 (t_7f451c5f_ui_doc.md, pageindex, pageindex_status=ok, has_tree=true)
#           选用理由: 历史 UI 验证测试 KB（改动卡 t_7f451c5f 自测产物）、已成功建树可作"重建后仍 ok"对照
#           注: 首轮曾选 e1c52f26(regress-kb-regress_972a19) 的 r3_third.md，实测该 KB 已被软删（is_deleted=true）
#               → reindex 返回 404「知识库不存在」；故改为"KB 未删除"的样本，并把 kb_deleted 纳入只读审计口径。
#   约束: 不触碰业务 KB（仅 GINA 疑似业务库，本脚本完全不含它）；不重启服务；不改代码。
#
# 接口:
#   GET  /api/v1/knowledge-bases/{kb}/documents/{doc}            前置/后置状态
#   POST /api/v1/knowledge-bases/{kb}/documents/{doc}/reindex    重建索引
#   POST /api/v1/knowledge-bases/{kb}/documents/{doc}/pageindex/rebuild
#   POST /api/v1/knowledge-bases/{kb}/search
# 首次执行: 2026-10-12T03:4x UTC（本次）
# 断言（任一 FAIL → 本用例 FAIL）:
#   B1 存量 embedding 文档 reindex → HTTP 200 且 data.index_type == "embedding"
#   B2 同文档 pageindex/rebuild → HTTP 400 且 message 含「不是 PageIndex 索引方式」
#   B3 轮询后 status == "indexed"、chunk_count > 0、meta.index_type 仍 == "embedding"
#   B4 search mode=vector → 命中该文档既有内容（items[].document_id == 目标 doc）
#   B5 存量 pageindex 文档 reindex → data.index_type == "pageindex"，轮询后 pageindex_status == "ok"
# 注意: 重复执行会再次触发重建索引；embedding 重建会按 chunk_index 追加新分块行（新增 chunk_id），
#       既有分块行不会删除 —— 该行为属改动前既有实现，本脚本记录前后行数作为观察项，不计入本用例 FAIL。
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

RAW=03-testing/evidence/raw
mkdir -p "$RAW"

KB_EMB="f380d232-9551-4bee-ad30-7a55606cab21"
DOC_EMB="99c37b1e-7183-4b1b-902d-e22c9070db82"
KB_PI="21f3f148-a8b2-404f-9412-7561ac5d6714"
DOC_PI="7b678d3f-1ccf-4883-93d9-549cd932ec19"
VQ="知识库管理系统是一个用于存储、检索和问答的智能系统"
RESULT="$RAW/PI-06_result.json"

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
contains() { case "$2" in *"$1"*) echo yes ;; *) echo no ;; esac; }

kb_login || exit 1

echo "==== PI-06 前置状态（只读）===="
curl -sS -m "$KB_TIMEOUT" "$BASE_URL/api/v1/knowledge-bases/$KB_EMB/documents/$DOC_EMB" \
  -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-06_pre_emb.json" -w 'HTTP_CODE=%{http_code}\n'
curl -sS -m "$KB_TIMEOUT" "$BASE_URL/api/v1/knowledge-bases/$KB_PI/documents/$DOC_PI" \
  -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-06_pre_pi.json" -w 'HTTP_CODE=%{http_code}\n'
echo "[pre S-EMB] $(jq -c '{file:.data.document.filename,status:.data.document.status,chunk_count:.data.document.chunk_count,index_type:.data.document.meta.index_type,has_tree:(.data.document.meta|has("pageindex_tree")),uploaded_at:.data.document.uploaded_at}' "$RAW/PI-06_pre_emb.json")"
echo "[pre S-PI ] $(jq -c '{file:.data.document.filename,status:.data.document.status,chunk_count:.data.document.chunk_count,index_type:.data.document.meta.index_type,pageindex_status:.data.document.meta.pageindex_status,has_tree:(.data.document.meta|has("pageindex_tree"))}' "$RAW/PI-06_pre_pi.json")"
backend/.venv/bin/python 03-testing/evidence/raw/probe_doc_chunks.py "$KB_EMB" --docs "$DOC_EMB" 2>&1 | tee "$RAW/PI-06_chunks_before.txt"

echo "==== PI-06 B1: 存量 embedding 文档 reindex ===="
curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_EMB/documents/$DOC_EMB/reindex" \
  -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-06_reindex_emb.json" \
  -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-06_reindex_emb.w"
jq -c '{code,message,data}' "$RAW/PI-06_reindex_emb.json"
IT_RE="$(jq -r '.data.index_type // "<absent>"' "$RAW/PI-06_reindex_emb.json")"
check B1 "reindex 响应 data.index_type 为 embedding（兜底分流）" "embedding" "$IT_RE"

echo "==== PI-06 B2: 同文档 pageindex/rebuild 应被拒绝 ===="
curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_EMB/documents/$DOC_EMB/pageindex/rebuild" \
  -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-06_pi_rebuild_reject.json" \
  -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-06_pi_rebuild_reject.w"
jq -c '{code,message,data}' "$RAW/PI-06_pi_rebuild_reject.json"
HTTP_RB="$(grep -o 'HTTP_CODE=[0-9]*' "$RAW/PI-06_pi_rebuild_reject.w" | cut -d= -f2)"
MSG_RB="$(jq -r '.message // ""' "$RAW/PI-06_pi_rebuild_reject.json")"
check B2a "pageindex/rebuild 返回 HTTP 400" "400" "$HTTP_RB"
check B2b "错误信息含「不是 PageIndex 索引方式」" "yes" "$(contains "不是 PageIndex 索引方式" "$MSG_RB")"

echo "==== PI-06 B3: 轮询重建后的存量 embedding 文档 ===="
k=0; FINALE=""; STE=""
while [ "$k" -lt 60 ]; do
  k=$((k + 1))
  curl -sS -m 30 "$BASE_URL/api/v1/knowledge-bases/$KB_EMB/documents/$DOC_EMB" \
    -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-06_emb_poll_$k.json" \
    -w "HTTP_CODE=%{http_code}\n" >> "$RAW/PI-06_emb_polls.log"
  FINALE="$RAW/PI-06_emb_poll_$k.json"
  STE="$(jq -r '.data.document.status // empty' "$FINALE")"
  echo "[poll-emb $k] t=$((k * 5))s status=$STE index_type=$(jq -r '.data.document.meta.index_type // "-"' "$FINALE") chunk_count=$(jq -r '.data.document.chunk_count // "-"' "$FINALE")"
  if [ "$STE" = "indexed" ] || [ "$STE" = "failed" ]; then break; fi
  sleep 5
done
cp -f "$FINALE" "$RAW/PI-06_emb_doc_final.json"
jq -c '{code,status:.data.document.status,chunk_count:.data.document.chunk_count,index_type:.data.document.meta.index_type,has_tree:(.data.document.meta|has("pageindex_tree")),error_message:.data.document.error_message}' "$RAW/PI-06_emb_doc_final.json"
STE="$(jq -r '.data.document.status // "<absent>"' "$RAW/PI-06_emb_doc_final.json")"
CCE="$(jq -r '.data.document.chunk_count // 0' "$RAW/PI-06_emb_doc_final.json")"
ITE="$(jq -r '.data.document.meta.index_type // "<absent>"' "$RAW/PI-06_emb_doc_final.json")"
check B3a "重建后 status 为 indexed" "indexed" "$STE"
if [ "${CCE:-0}" -gt 0 ] 2>/dev/null; then CCV="gt0"; else CCV="eq0"; fi
check B3b "重建后 chunk_count > 0（actual=$CCE）" "gt0" "$CCV"
check B3c "重建后 meta.index_type 仍为 embedding（未被改写）" "embedding" "$ITE"

echo "==== PI-06 B4: 重建后向量检索仍命中该文档既有内容 ===="
curl -sS -m 120 -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_EMB/search" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KB_TOKEN" \
  -d "{\"query\":\"$VQ\",\"mode\":\"vector\",\"top_k\":5}" \
  -o "$RAW/PI-06_search_vector.json" -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-06_search_vector.w"
TOTV="$(jq -r '.data.total // 0' "$RAW/PI-06_search_vector.json")"
HITV="$(jq -r --arg d "$DOC_EMB" '[.data.items[]? | select(.document_id==$d)] | length' "$RAW/PI-06_search_vector.json")"
echo "[search-vector] total=$TOTV 命中目标文档=$HITV items=$(jq -c '[.data.items[]?|{document_id,filename,score,match_type}]' "$RAW/PI-06_search_vector.json")"
if [ "${TOTV:-0}" -ge 1 ] && [ "${HITV:-0}" -ge 1 ]; then V="PASS"; else V="FAIL"; FAILS=$((FAILS + 1)); fi
CHECKS+=("{\"id\":\"B4\",\"desc\":\"重建后 mode=vector 命中目标文档既有内容\",\"expected\":\"total>=1 && 命中目标>=1\",\"actual\":\"total=$TOTV hit=$HITV\",\"verdict\":\"$V\"}")
echo "[B4] $V  search mode=vector (total=$TOTV hit=$HITV)"
backend/.venv/bin/python 03-testing/evidence/raw/probe_doc_chunks.py "$KB_EMB" --docs "$DOC_EMB" 2>&1 | tee "$RAW/PI-06_chunks_after.txt"

echo "==== PI-06 B5: 存量 pageindex 文档 reindex ===="
curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_PI/documents/$DOC_PI/reindex" \
  -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-06_reindex_pi.json" \
  -w 'HTTP_CODE=%{http_code} TIME=%{time_total}s\n' | tee "$RAW/PI-06_reindex_pi.w"
jq -c '{code,message,data}' "$RAW/PI-06_reindex_pi.json"
IT_PI="$(jq -r '.data.index_type // "<absent>"' "$RAW/PI-06_reindex_pi.json")"
check B5a "存量 pageindex 文档 reindex 响应 index_type 为 pageindex" "pageindex" "$IT_PI"

m=0; FINALP=""; PISP=""
while [ "$m" -lt 90 ]; do
  m=$((m + 1))
  curl -sS -m 30 "$BASE_URL/api/v1/knowledge-bases/$KB_PI/documents/$DOC_PI" \
    -H "Authorization: Bearer $KB_TOKEN" -o "$RAW/PI-06_pi_poll_$m.json" \
    -w "HTTP_CODE=%{http_code}\n" >> "$RAW/PI-06_pi_polls.log"
  FINALP="$RAW/PI-06_pi_poll_$m.json"
  PISP="$(jq -r '.data.document.meta.pageindex_status // empty' "$FINALP")"
  echo "[poll-pi $m] t=$((m * 5))s status=$(jq -r '.data.document.status // "-"' "$FINALP") pageindex_status=$PISP"
  if [ "$PISP" = "ok" ] || [ "$PISP" = "failed" ] || [ "$PISP" = "degraded" ]; then break; fi
  sleep 5
done
cp -f "$FINALP" "$RAW/PI-06_pi_doc_final.json"
jq -c '{code,status:.data.document.status,index_type:.data.document.meta.index_type,pageindex_status:.data.document.meta.pageindex_status,has_tree:(.data.document.meta|has("pageindex_tree")),node_count:.data.document.meta.pageindex_tree.node_count}' "$RAW/PI-06_pi_doc_final.json"
PISP="$(jq -r '.data.document.meta.pageindex_status // "<absent>"' "$RAW/PI-06_pi_doc_final.json")"
ITP2="$(jq -r '.data.document.meta.index_type // "<absent>"' "$RAW/PI-06_pi_doc_final.json")"
check B5b "存量 pageindex 文档重建后 pageindex_status 为 ok" "ok" "$PISP"
check B5c "存量 pageindex 文档重建后 index_type 仍为 pageindex" "pageindex" "$ITP2"

VERDICT="PASS"; [ "$FAILS" -gt 0 ] && VERDICT="FAIL"
printf '%s\n' "${CHECKS[@]}" > "$RAW/PI-06_checks.jsonl"
jq -n --arg v "$VERDICT" --argjson fails "$FAILS" \
      --arg kb1 "$KB_EMB" --arg kb2 "$KB_PI" --arg d1 "$DOC_EMB" --arg d2 "$DOC_PI" \
      --slurpfile checks "$RAW/PI-06_checks.jsonl" \
      '{case:"PI-06", verdict:$v, fails:$fails,
        sample_embedding:{kb:$kb1,doc:$d1}, sample_pageindex:{kb:$kb2,doc:$d2},
        checks:$checks, generated_at:"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}' > "$RESULT"
echo "==== PI-06 DONE  verdict=$VERDICT fails=$FAILS ===="
echo "[summary] $RESULT"
exit 0
