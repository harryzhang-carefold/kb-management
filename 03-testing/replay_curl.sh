#!/usr/bin/env bash
# Replay all curl cases with token from file
set -e
export TOKEN=*** /tmp/kb_token.txt)
cd /home/harry.zhang/kb-management/03-testing/curl
echo "TOKEN len=${#TOKEN}"
echo "=== REPLAY AC2 (pageindex search) ==="
bash case_ac2_search_pageindex.sh 2>&1 | head -30
echo ""
echo "=== REPLAY AC4 (regression hybrid/vector/keyword) ==="
bash case_ac4_regression.sh 2>&1 | head -50
