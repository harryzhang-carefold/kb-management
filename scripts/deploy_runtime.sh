#!/usr/bin/env bash
# Run from a Git checkout that has fast-forwarded to the approved commit.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
backend/.venv/bin/python -m pip install -r backend/requirements.lock.txt
backend/.venv/bin/python scripts/migrate_schema.py
mkdir -p "$HOME/.config/systemd/user"
for entry in 'kb-api-9012:start_backend' 'kb-worker:start_worker' 'kb-mcp-9100:start_mcp'; do
  name="${entry%%:*}"
  launcher="${entry#*:}"
  cat > "$HOME/.config/systemd/user/$name.service" <<EOF
[Unit]
Description=kb-management $name
After=network-online.target
[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=/bin/bash $PROJECT_DIR/scripts/$launcher.sh
Restart=on-failure
RestartSec=5
TimeoutStopSec=120
[Install]
WantedBy=default.target
EOF
done
systemctl --user stop kb-mcp-9100.service kb-api-9012.service kb-worker.service || true
# Stop only legacy launcher processes from this exact checkout, gracefully.
backend/.venv/bin/python - "$PROJECT_DIR" <<'PY'
import os, signal, subprocess, sys, time
root = sys.argv[1] + '/backend/.venv/bin/'
pids = []
parents = {}
for line in subprocess.check_output(['ps', '-u', str(os.getuid()), '-o', 'pid=,ppid=,args='], text=True).splitlines():
    pid, parent, command = line.strip().split(None, 2)
    if (root + 'uvicorn ') in command or (root + 'celery ') in command:
        parents[int(pid)] = int(parent)
for pid, parent in parents.items():
    if parent not in parents:
        os.kill(pid, signal.SIGTERM); pids.append(pid)
for _ in range(120):
    active = []
    for pid in pids:
        try: os.kill(pid, 0); active.append(pid)
        except ProcessLookupError: pass
    if not active: break
    time.sleep(1)
else:
    raise SystemExit('Legacy worker is still draining; leave it intact and retry after its current job completes')
PY
systemctl --user daemon-reload
systemctl --user enable --now kb-api-9012.service kb-worker.service kb-mcp-9100.service
cd frontend
npm ci --no-audit --no-fund
npm run build
TARGET_DIR="${KB_FRONTEND_TARGET:-$PROJECT_DIR/02-development/deploy/dist}"
mkdir -p "$TARGET_DIR"
rsync -a --delete dist/ "$TARGET_DIR/"
find "$TARGET_DIR" -type d -exec chmod 755 {} +
find "$TARGET_DIR" -type f -exec chmod 644 {} +
printf 'KB API, worker, MCP and frontend deployed from commit '
git -C "$PROJECT_DIR" rev-parse HEAD
