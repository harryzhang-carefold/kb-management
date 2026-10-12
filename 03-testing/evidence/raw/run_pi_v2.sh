#!/usr/bin/env bash
# 运行 VI-PI-2 用例并汇总证据（非用例脚本，仅调度 + 追加日志）
# KB 已在 2026-10-12T03:29:53Z 由 setup_pi_v2_kb.sh 建好（见 raw/kb_create_PI-V2.json），此处不重复建库。
cd /home/harry.zhang/kb-management || exit 1
export KB_ID="${KB_ID:-32b1101f-efd6-467c-900a-255c75656791}"
LOG=03-testing/evidence/PI-V2_case1_case3.txt
printf '########## PI-V2 证据全文 (t_32351222) ##########\n' > "$LOG"
printf 'KB_ID=%s\n' "$KB_ID" >> "$LOG"
printf '开始(UTC): %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
printf 'KB 创建证据: 03-testing/evidence/raw/kb_create_PI-V2.json (2026-10-12T03:29:53Z)\n' >> "$LOG"

run_step() {
  local name="$1"; shift
  printf '\n\n==================== %s ====================\n' "$name" >> "$LOG"
  printf '[step-start %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$name" >> "$LOG"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  printf '[step-end %s] %s rc=%d\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$name" "$rc" >> "$LOG"
  return $rc
}

run_step "PI-01 默认上传（不传 index_type）"  bash 03-testing/curl/case_PI-01_upload_default.sh
run_step "PI-02 pageindex 检索"              bash 03-testing/curl/case_PI-02_search_pageindex.sh
run_step "PI-03 pageindex 问答(SSE)+观察项"   bash 03-testing/curl/case_PI-03_chat_pageindex.sh

printf '\n[ALL DONE] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "[runner] 完成，日志: $LOG"
