#!/usr/bin/env bash
# kb-management MCP Server 启动脚本
#
# ⚠️ mcp 库依赖说明（A2）：
#   mcp 2.3.0 要求 pydantic>=2.12，主 venv 的 FastAPI backend 用 pydantic 2.9.2，
#   两者不能共存于同一 venv。本脚本通过 MCP_STAGE 指向一个只含 mcp 及其依赖
#   的 wheel 目录（PYTHONPATH 隔离），不污染主 venv。
#   - 默认 MCP_STAGE 指向 05-temp/mcpstage（A4 常驻化沿用该隔离目录；
#     05-temp 不进 git，若目录缺失本脚本会在下方校验并退出，不静默降级）。
set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/backend"

# mcp 库的隔离依赖目录（默认 A4 常驻目录 05-temp/mcpstage）
MCP_STAGE="${MCP_STAGE:-$REPO_ROOT/05-temp/mcpstage}"
if [ ! -d "$MCP_STAGE" ]; then
    echo "[mcp] ERROR: MCP_STAGE 目录不存在：$MCP_STAGE（mcp 2.3.0 与主 venv pydantic 冲突，必须隔离加载，见 A4 DEPLOY 文档）" >&2
    exit 1
fi
export PYTHONPATH="$MCP_STAGE${PYTHONPATH:+:$PYTHONPATH}"

# 主 venv 提供 FastAPI/uvicorn 及 app.* 依赖（mcp/pydantic 由 PYTHONPATH 隔离目录提供）
source .venv/bin/activate

# infra/.env 存在性校验（值由 app.core.config 的 pydantic env_file 直接加载，
# 不在 shell 里 source——.env 里有含空格未加引号的值，source 会炸。
# 与 9012 的 config.py 同源，保证 9100 与 9012 读到同一份配置）
ENV_FILE="$REPO_ROOT/infra/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "[mcp] ERROR: 未找到 $ENV_FILE（生产必须注入 KB_MCP_API_KEY）" >&2
    exit 1
fi

# 鉴权密钥（V2 §6.2）：仅检查是否配置，值不打印
KB_MCP_API_KEY_SET=$(python -c "
import sys
sys.path.insert(0, '$REPO_ROOT/05-temp/mcpstage')
from dotenv import dotenv_values
print(bool(dotenv_values('$ENV_FILE').get('KB_MCP_API_KEY')))
")
if [ "$KB_MCP_API_KEY_SET" != "True" ]; then
    echo "[mcp] WARNING: KB_MCP_API_KEY 未设置，MCP 鉴权中间件处于放行状态（仅限本地开发）"
fi

echo "[mcp] starting kb-management MCP Server on :9100 (auth: $([ "$KB_MCP_API_KEY_SET" = "True" ] && echo on || echo OFF))"
# --proxy-headers：0.0.0.0 绑定时 uvicorn 默认 Host 白名单仅 127.0.0.1，
# agent 容器经 172.19.0.1:9100 访问会 421 Invalid Host header。开启 proxy
# 头信任后 Host 校验按转发头放行（内网桥网，风险见 DEPLOY 文档 §9100）。
exec uvicorn mcp_server:streamable_app --host 0.0.0.0 --port 9100 --log-level info --proxy-headers
