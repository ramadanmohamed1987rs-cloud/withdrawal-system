#!/bin/bash
# ===================================================
# Deploy files to Oracle Cloud VM
# Usage: ./deploy.sh USER@SERVER_IP
# ===================================================
set -e

if [ -z "$1" ]; then
    echo "Usage: ./deploy.sh USER@SERVER_IP"
    echo "Example: ./deploy.sh ubuntu@129.154.xx.xx"
    exit 1
fi

SERVER="$1"
DEPLOY_DIR="/opt/withdrawal"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deploying to $SERVER ==="

echo "[1/4] Uploading server files..."
scp "$SCRIPT_DIR/server.py" "$SERVER:$DEPLOY_DIR/server.py"
scp "$SCRIPT_DIR/requirements.txt" "$SERVER:$DEPLOY_DIR/requirements.txt"

echo "[2/4] Uploading web files..."
ssh "$SERVER" "mkdir -p $DEPLOY_DIR/web"
scp -r "$SCRIPT_DIR/web/"* "$SERVER:$DEPLOY_DIR/web/"

echo "[3/4] Installing dependencies..."
ssh "$SERVER" "sudo -u withdrawal $DEPLOY_DIR/venv/bin/pip install -r $DEPLOY_DIR/requirements.txt"

echo "[4/4] Restarting service..."
ssh "$SERVER" "sudo systemctl restart withdrawal"

echo ""
echo "=== Deploy complete! ==="
echo "Service: http://$(echo $SERVER | cut -d@ -f2)"
