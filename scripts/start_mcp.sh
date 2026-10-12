#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/backend"
source .venv/bin/activate
python -c "from app.core.config import settings; assert len(settings.kb_mcp_api_key.encode()) >= 32, 'Knowledge MCP service credential required'"
exec uvicorn mcp_server:streamable_app --host 0.0.0.0 --port 9100 --log-level info --proxy-headers
