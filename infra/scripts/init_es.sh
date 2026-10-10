#!/bin/bash
# ============================================================
# kb-management — ES ik 分词器安装脚本
# 在 ES 容器首次启动后执行一次（可重复）
# 用法: docker exec kb-es bash /tmp/init_es.sh  或  bash scripts/init_es.sh
# ============================================================
set -e

IK_VERSION="8.13.4"
ES_PLUGIN_DIR="/usr/share/elasticsearch/plugins"

echo "[init_es] Checking if ik plugin already installed..."
if [ -d "$ES_PLUGIN_DIR/analysis-ik" ]; then
    echo "[init_es] ik plugin already present, skipping."
    exit 0
fi

echo "[init_es] Installing elasticsearch-analysis-ik for v${IK_VERSION}..."
cd "$ES_PLUGIN_DIR"
curl -sL -o /tmp/ik.zip \
  "https://get.infini.cloud/elasticsearch/analysis-ik/${IK_VERSION}"

if [ ! -f /tmp/ik.zip ] || [ "$(stat -c%s /tmp/ik.zip 2>/dev/null || echo 0)" -lt 1000 ]; then
    echo "[init_es] ERROR: download failed. Try manual install:"
    echo "  curl -O https://get.infini.cloud/elasticsearch/analysis-ik/${IK_VERSION}"
    exit 1
fi

unzip -q /tmp/ik.zip -d "$ES_PLUGIN_DIR/"
rm -f /tmp/ik.zip
echo "[init_es] ik plugin installed at $ES_PLUGIN_DIR/analysis-ik"
echo "[init_es] NOTE: restart ES to load the plugin (docker restart kb-es)"
