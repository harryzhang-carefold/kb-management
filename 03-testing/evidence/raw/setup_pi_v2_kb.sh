#!/usr/bin/env bash
# =============================================================================
# setup_pi_v2_kb.sh — VI-PI-2 (t_32351222) 前置：建自建测试 KB
# 用例: (前置，非断言用例)
# 接口: POST /api/v1/knowledge-bases
# 入参: {"name":"验证-默认pageindex-VI-PI-2-<HHMMSS>","description":"VI-PI-2 独立验证自建库"}
# 首次执行: 2026-10-12T03:2x UTC
# 说明: 只新建自建测试 KB（名字带 VI-PI-2 + 时间戳），不碰他人/存量 KB。
#       原始响应写入 03-testing/evidence/raw/kb_create_PI-V2.json
# =============================================================================
set -uo pipefail
cd /home/harry.zhang/kb-management
source 03-testing/curl/lib/kb_common.sh

kb_login || exit 1

TS="$(date -u +%H%M%S)"
KB_NAME="验证-默认pageindex-VI-PI-2-${TS}"

curl -sS -m 30 -X POST "$BASE_URL/api/v1/knowledge-bases" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -d "{\"name\":\"${KB_NAME}\",\"description\":\"VI-PI-2 独立验证自建库（用例1+3）\"}" \
  -o 03-testing/evidence/raw/kb_create_PI-V2.json \
  -w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'

echo "[setup] KB_NAME=$KB_NAME"
