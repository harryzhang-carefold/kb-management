#!/bin/bash
# Deploy KBMS frontend to NPM container
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$PROJECT_DIR/frontend/dist"
NPM_CONTAINER="nginx-proxy-manager-app-1"
TARGET_DIR="/srv/kb-management"

echo "Building frontend..."
cd "$PROJECT_DIR/frontend"
npm run build

echo "Removing crossorigin from index.html..."
sed -i 's/crossorigin //g' "$DIST_DIR/index.html"

echo "Deploying to $NPM_CONTAINER:$TARGET_DIR..."
docker exec "$NPM_CONTAINER" sh -c "rm -rf $TARGET_DIR/assets && mkdir -p $TARGET_DIR"
docker cp "$DIST_DIR/." "$NPM_CONTAINER:$TARGET_DIR/"
docker exec "$NPM_CONTAINER" chmod -R 644 "$TARGET_DIR/"

echo "Purging NPM cache..."
docker exec "$NPM_CONTAINER" sh -c 'find /var/lib/nginx/cache -type f -delete' 2>/dev/null || true

echo "Reloading Nginx..."
docker exec "$NPM_CONTAINER" nginx -s reload

echo "✅ Deployment complete"
echo "   URL: https://agent.carefold.ai/kb-management/"
echo "   User: admin / Admin@123"
