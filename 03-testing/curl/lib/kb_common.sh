#!/usr/bin/env bash
# =============================================================================
# kb_common.sh — kb-management curl 用例公共脚手架（VI-PI 验证批及后续复用）
#
# 用法（在用例脚本中 source 本文件，不要直接执行）：
#   source "$(dirname "$0")/lib/kb_common.sh"
#   kb_login                     # 登录取 token，只回显长度，不打印 token
#   kb_post "/api/v1/knowledge-bases" '{"name":"x"}'   # 自动带 Authorization
#   kb_get  "/api/v1/knowledge-bases"
#
# 环境变量（全部可覆盖，端点/账号一律走变量，不硬编码到逻辑里）：
#   BASE_URL   默认 http://127.0.0.1:9012       后端直连端口
#   KB_USER    默认 admin                       来源：仓库 tests/e2e_test.py:26-27 的测试账号
#   KB_PASS    默认 Admin@123                   同上（仓库自带测试账号，非生产密钥）
#   KB_TOKEN   已持有的 access_token；设置后 kb_login 可跳过
#
# 约束：本文件只做封装，不打印任何凭据全文（token 只回显长度）。
# 首次编写：2026-10-12（PI-V1，卡 t_fa5d836a），只做脚手架、未执行任何用例判定。
# =============================================================================

BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"
KB_USER="${KB_USER:-admin}"          # tests/e2e_test.py: "2. Login (admin/Admin@123)"
KB_PASS="${KB_PASS:-Admin@123}"      # 同上；如环境已改密，export KB_USER/KB_PASS 覆盖
KB_TOKEN="${KB_TOKEN:-}"

# 默认超时：登录/普通读 30s，上传/建树类可自行加 -m
KB_TIMEOUT="${KB_TIMEOUT:-60}"

# 统一 curl 结尾输出：HTTP 状态码 + 耗时，便于复测直接对比
KB_WRITE_OUT='\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'

# ---------------------------------------------------------------------------
# 内部：鉴权头（数组形式传参，避免 token 出现在 echo 里）
# ---------------------------------------------------------------------------
_kb_auth_hdr() {
  if [ -n "$KB_TOKEN" ]; then
    printf -- '-H\nAuthorization: Bearer %s\n' "$KB_TOKEN"
  fi
}

kb_require_token() {
  if [ -z "$KB_TOKEN" ]; then
    echo "[kb] 未持有 token，请先调用 kb_login（或 export KB_TOKEN=...）" >&2
    return 1
  fi
}

# ---------------------------------------------------------------------------
# kb_login — 登录取 access_token，写入全局 KB_TOKEN 并 export；只回显长度
# 接口: POST /api/v1/auth/login  {"username":KB_USER,"password":KB_PASS}
# ---------------------------------------------------------------------------
kb_login() {
  local resp
  resp="$(curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL/api/v1/auth/login" \
      -H 'Content-Type: application/json' \
      -d "{\"username\":\"$KB_USER\",\"password\":\"$KB_PASS\"}" \
      -w '\nHTTP_CODE=%{http_code}' 2>&1)" || {
    echo "[kb_login] FAIL: curl 执行失败（后端 $BASE_URL 是否在跑？）" >&2
    return 1
  }
  local code token
  code="$(printf '%s' "$resp" | tail -n1)"
  token="$(printf '%s' "$resp" | sed '$d' | jq -r '.data.access_token // empty' 2>/dev/null)"
  if [ -z "$token" ]; then
    echo "[kb_login] FAIL: $code $(printf '%s' "$resp" | sed '$d' | jq -c '{code,message}' 2>/dev/null)" >&2
    return 1
  fi
  KB_TOKEN="$token"
  export KB_TOKEN
  echo "[kb_login] OK $code user=$KB_USER token_len=${#KB_TOKEN} base=$BASE_URL"
}

# ---------------------------------------------------------------------------
# kb_post <path> [json-body] [extra curl args...]
#   path     形如 /api/v1/knowledge-bases/xxx/search
#   json-body  JSON 字符串；省略则不发送 body（如空 POST）
# ---------------------------------------------------------------------------
kb_post() {
  local path="$1"; shift
  kb_require_token || return 1
  local body=""; local has_body=0
  if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then body="$1"; has_body=1; shift; fi
  local auth_args=(); local line
  while IFS= read -r line; do auth_args+=("$line"); done < <(_kb_auth_hdr)
  if [ "$has_body" = "1" ]; then
    curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL$path" \
      -H "Content-Type: application/json" "${auth_args[@]}" \
      -d "$body" "$@" -w "$KB_WRITE_OUT"
  else
    curl -sS -m "$KB_TIMEOUT" -X POST "$BASE_URL$path" \
      "${auth_args[@]}" "$@" -w "$KB_WRITE_OUT"
  fi
}

# ---------------------------------------------------------------------------
# kb_get <path> [extra curl args...]
# ---------------------------------------------------------------------------
kb_get() {
  local path="$1"; shift
  kb_require_token || return 1
  local auth_args=(); local line
  while IFS= read -r line; do auth_args+=("$line"); done < <(_kb_auth_hdr)
  curl -sS -m "$KB_TIMEOUT" "$BASE_URL$path" "${auth_args[@]}" "$@" -w "$KB_WRITE_OUT"
}

# ---------------------------------------------------------------------------
# kb_multipart_post <path> -F ... 
#   上传接口用（multipart/form-data），调用方自行给全 -F 参数
# ---------------------------------------------------------------------------
kb_multipart_post() {
  local path="$1"; shift
  kb_require_token || return 1
  local auth_args=(); local line
  while IFS= read -r line; do auth_args+=("$line"); done < <(_kb_auth_hdr)
  curl -sS -m "${KB_UPLOAD_TIMEOUT:-300}" -X POST "$BASE_URL$path" \
    "${auth_args[@]}" "$@" -w "$KB_WRITE_OUT"
}
