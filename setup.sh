#!/bin/bash
# First-boot setup for plan-state synchronizer.
# Run this AFTER 'docker compose up -d' and the setup wizard.
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$COMPOSE_DIR"

echo "=== Plan-State Synchronizer Setup ==="
echo ""

# ── 1. Check prerequisites ──────────────────────────────────
if ! docker compose ps --status running | grep -q gideon-gateway; then
    echo "ERROR: gideon-gateway container is not running."
    echo "Run: docker compose up -d"
    exit 1
fi

echo "[1/6] Gateway container is running."

# ── 2. Initialize SQLite database ───────────────────────────
if docker exec gideon-gateway test -f /opt/plansync/plansync.db; then
    echo "[2/6] Database already exists, skipping init."
else
    echo "[2/6] Initializing SQLite database..."
    docker exec gideon-gateway python3 /opt/plansync/init-db.py
fi

# ── 3. Install Python dependencies for MCP server ───────────
echo "[3/6] Checking MCP server dependencies..."
docker exec gideon-gateway python3 -c "import mcp" 2>/dev/null \
    && echo "  mcp already installed" \
    || docker exec gideon-gateway /opt/hermes/.venv/bin/python3 -m pip install -q -r /opt/plansync/mcp-server/requirements.txt

# ── 4. Install sync script dependencies ─────────────────────
echo "[4/6] Installing sync script dependencies..."
docker exec gideon-gateway python3 -c "import requests; import todoist_api_python" 2>/dev/null \
    && echo "  dependencies already installed" \
    || docker exec gideon-gateway /opt/hermes/.venv/bin/python3 -m pip install -q -r /opt/plansync/sync/requirements.txt

# ── 5. Register MCP server with Hermes ──────────────────────
echo "[5/6] Registering plansync MCP server..."
docker exec gideon-gateway hermes mcp add plansync \
    --command python3 \
    --args "/opt/plansync/mcp-server/server.py" \
    --env PLANSYNC_DB=/opt/plansync/plansync.db \
    2>/dev/null || echo "  (MCP server may already be registered via config.yaml)"

# ── 6. Register cron jobs ───────────────────────────────────
echo "[6/6] Registering cron jobs..."
docker exec gideon-gateway hermes cron create "0 6 * * *" \
    --no-agent \
    --script daily-sync.py \
    --deliver telegram \
    --name "plan-sync" \
    2>/dev/null || echo "  (plan-sync cron may already exist)"

docker exec gideon-gateway hermes cron create "15 6 * * *" \
    --script briefing-context.sh \
    --deliver telegram \
    --skill plansync-briefing \
    --name "morning-briefing" \
    2>/dev/null || echo "  (morning-briefing cron may already exist)"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Smoke test:"
echo "  docker exec -it gideon-gateway hermes chat -q 'Hello, confirm you are working'"
echo ""
echo "Test MCP tools:"
echo '  docker exec -it gideon-gateway hermes chat -q "Use the plansync tools to list domains"'
echo ""
echo "Security checklist: review SECURITY-CHECKLIST.md"
