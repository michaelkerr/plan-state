#!/bin/bash
# Register plan-state application with a running Gideon instance.
# Run this after 'docker compose up -d' from the gideon repo.
#
# WHEN TO RE-RUN:
#   - After changing skills/*.md or scripts/*.py (these are copied to gideon/data/)
#   - After adding new MCP tools or cron jobs
#
# NO RE-RUN NEEDED:
#   - Editing mcp-server/server.py, sync/daily_sync.py, schema.sql
#     (volume-mounted directly, changes are live immediately)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GIDEON_DATA="${GIDEON_DATA:-$SCRIPT_DIR/../gideon/data}"
CONTAINER="${GIDEON_CONTAINER:-gideon-gateway}"

echo "=== Plan-State Registration ==="
echo "  Gideon data: $GIDEON_DATA"
echo "  Container:   $CONTAINER"
echo ""

# ── 1. Check prerequisites ──────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: $CONTAINER container is not running."
    echo "Start Gideon first: cd ../gideon && docker compose up -d"
    exit 1
fi
echo "[1/8] Container is running."

# ── 2. Copy skills ──────────────────────────────────────────
echo "[2/8] Installing skills..."
cp "$SCRIPT_DIR/skills/"*.md "$GIDEON_DATA/skills/"
echo "  Copied: $(ls "$SCRIPT_DIR/skills/"*.md | xargs -n1 basename | tr '\n' ' ')"

# ── 3. Copy cron wrapper scripts ────────────────────────────
echo "[3/8] Installing scripts..."
cp "$SCRIPT_DIR/scripts/"*.py "$GIDEON_DATA/scripts/"
cp "$SCRIPT_DIR/scripts/"*.sh "$GIDEON_DATA/scripts/"
echo "  Copied: $(ls "$SCRIPT_DIR/scripts/"*.py "$SCRIPT_DIR/scripts/"*.sh | xargs -n1 basename | tr '\n' ' ')"

# ── 4. Initialize database ──────────────────────────────────
if docker exec "$CONTAINER" test -f /opt/plansync/plansync.db; then
    echo "[4/8] Database already exists, skipping init."
else
    echo "[4/8] Initializing SQLite database..."
    docker exec "$CONTAINER" python3 /opt/plansync/init-db.py
fi

# ── 5. Install MCP server dependencies ──────────────────────
echo "[5/8] Checking MCP server dependencies..."
docker exec "$CONTAINER" python3 -c "import mcp" 2>/dev/null \
    && echo "  mcp already installed" \
    || docker exec "$CONTAINER" /opt/hermes/.venv/bin/python3 -m pip install -q -r /opt/plansync/mcp-server/requirements.txt

# ── 6. Install sync dependencies ────────────────────────────
echo "[6/8] Checking sync dependencies..."
docker exec "$CONTAINER" python3 -c "import requests; import todoist_api_python" 2>/dev/null \
    && echo "  dependencies already installed" \
    || docker exec "$CONTAINER" /opt/hermes/.venv/bin/python3 -m pip install -q -r /opt/plansync/sync/requirements.txt

# ── 7. Register MCP server ──────────────────────────────────
echo "[7/8] Registering plansync MCP server..."
yes | docker exec -i "$CONTAINER" hermes mcp add plansync \
    --command python3 \
    --args "/opt/plansync/mcp-server/server.py" \
    --env PLANSYNC_DB=/opt/plansync/plansync.db \
    2>/dev/null || echo "  (MCP server may already be registered)"

# ── 8. Register cron jobs ────────────────────────────────────
echo "[8/8] Registering cron jobs..."
docker exec "$CONTAINER" hermes cron create "0 6 * * *" \
    --no-agent \
    --script daily-sync.py \
    --deliver telegram \
    --name "plan-sync" \
    2>/dev/null || echo "  (plan-sync cron may already exist)"

docker exec "$CONTAINER" hermes cron create "15 6 * * *" \
    --script briefing-context.sh \
    --deliver telegram \
    --skill plansync-briefing \
    --name "morning-briefing" \
    2>/dev/null || echo "  (morning-briefing cron may already exist)"

echo ""
echo "=== Registration Complete ==="
echo ""
echo "Verify:"
echo "  docker exec -it $CONTAINER hermes chat -q 'Use the plansync tools to list domains'"
echo ""
echo "Required env vars in gideon/.env:"
echo "  TODOIST_API_KEY, OPENWEATHERMAP_API_KEY"
