#!/usr/bin/env bash
# kb-management MCP Server 启动脚本
set -e
cd "$(dirname "$0")/../backend"
source .venv/bin/activate

echo "[mcp] starting kb-management MCP Server on :9100"
exec uvicorn mcp_server:streamable_app --host 0.0.0.0 --port 9100 --log-level info
