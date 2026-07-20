#!/bin/bash
# Register plan-state application with a running Gideon instance.
# Run this after 'docker compose up -d' from the gideon repo.
#
# Skills are loaded automatically via external_dirs in Gideon's config.yaml.
# MCP server is configured in Gideon's config.yaml (mcp_servers.plansync).
# Both use the /opt/plansync volume mount — edits are live immediately.
#
# WHEN TO RE-RUN:
#   - After adding new cron jobs
#   - After changing scripts/*.py or *.sh (these are thin wrappers copied
#     into the container; Hermes blocks symlinks outside /opt/data/scripts/)
#
# NO RE-RUN NEEDED:
#   - Editing skills/*.md (loaded via external_dirs, live immediately)
#   - Editing mcp-server/server.py, sync/daily_sync.py, schema.sql
#     (volume-mounted directly, live immediately)
#   - Editing the code that scripts delegate to (sync/daily_sync.py etc.
#     is volume-mounted, so changes are live even though the wrapper is copied)
set -euo pipefail

CONTAINER="${GIDEON_CONTAINER:-gideon-gateway}"

echo "=== Plan-State Registration ==="
echo "  Container: $CONTAINER"
echo ""

# ── 1. Check prerequisites ──────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: $CONTAINER container is not running."
    echo "Start Gideon first: cd ../gideon && docker compose up -d"
    exit 1
fi
echo "[1/6] Container is running."

# ── 2. Clean up old copied files (skills now via external_dirs, scripts now symlinked) ──
echo "[2/6] Cleaning stale copies..."
for skill in plansync.md plansync-briefing.md domain-authoring.md; do
    target="/opt/data/skills/$skill"
    if docker exec "$CONTAINER" test -f "$target" -a ! -L "$target" 2>/dev/null; then
        docker exec "$CONTAINER" rm "$target"
        echo "  Removed old skill copy: $skill"
    fi
done
for script in daily-sync.py briefing-context.py briefing-context.sh evening-nudge.py; do
    target="/opt/data/scripts/$script"
    if docker exec "$CONTAINER" test -L "$target" 2>/dev/null; then
        docker exec "$CONTAINER" rm "$target"
        echo "  Removed stale symlink: $script"
    fi
done

# ── 3. Copy cron wrapper scripts ────────────────────────────
# Hermes requires scripts to resolve within /opt/data/scripts/ (no symlinks
# to external paths). These are thin wrappers that delegate to volume-mounted
# code, so the actual logic is still live-editable.
echo "[3/6] Copying scripts..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
for script in "$SCRIPT_DIR"/scripts/*.py "$SCRIPT_DIR"/scripts/*.sh; do
    [ -f "$script" ] || continue
    name=$(basename "$script")
    docker exec -i "$CONTAINER" tee "/opt/data/scripts/$name" > /dev/null < "$script"
    echo "  $name"
done

# ── 4. Initialize database ──────────────────────────────────
if docker exec "$CONTAINER" test -f /opt/plansync/plansync.db; then
    echo "[4/6] Database already exists, skipping init."
else
    echo "[4/6] Initializing SQLite database..."
    docker exec "$CONTAINER" python3 /opt/plansync/init-db.py
fi

# ── 5. Install Python dependencies ──────────────────────────
echo "[5/6] Checking dependencies..."
docker exec "$CONTAINER" python3 -c "import mcp" 2>/dev/null \
    && echo "  mcp already installed" \
    || docker exec "$CONTAINER" /opt/hermes/.venv/bin/python3 -m pip install -q -r /opt/plansync/mcp-server/requirements.txt
docker exec "$CONTAINER" python3 -c "import requests" 2>/dev/null \
    && echo "  sync deps already installed" \
    || docker exec "$CONTAINER" /opt/hermes/.venv/bin/python3 -m pip install -q -r /opt/plansync/sync/requirements.txt

# ── 6. Register cron jobs ────────────────────────────────────
echo "[6/6] Registering cron jobs..."
existing_jobs=$(docker exec "$CONTAINER" hermes cron list 2>/dev/null)

if echo "$existing_jobs" | grep -q "plan-sync"; then
    echo "  plan-sync cron already exists"
else
    docker exec "$CONTAINER" hermes cron create "0 6 * * *" \
        --no-agent \
        --script daily-sync.py \
        --deliver telegram \
        --name "plan-sync"
fi

if echo "$existing_jobs" | grep -q "morning-briefing"; then
    echo "  morning-briefing cron already exists"
else
    docker exec "$CONTAINER" hermes cron create "15 6 * * *" \
        --script briefing-context.sh \
        --deliver telegram \
        --skill plansync-briefing \
        --name "morning-briefing"
fi

if echo "$existing_jobs" | grep -q "evening-nudge"; then
    echo "  evening-nudge cron already exists"
else
    docker exec "$CONTAINER" hermes cron create "0 17 * * *" \
        --no-agent \
        --script evening-nudge.py \
        --deliver telegram \
        --name "evening-nudge"
fi

echo ""
echo "=== Registration Complete ==="
echo ""
echo "Skills:     loaded via external_dirs (live edits)"
echo "Scripts:    copied (re-run register.sh after edits to wrappers)"
echo "MCP server: configured in Gideon config.yaml (live edits)"
echo "Cron jobs:  registered"
echo ""
echo "Verify:"
echo "  docker exec -it $CONTAINER hermes chat -q 'Use the plansync tools to list domains'"
echo ""
echo "Required env vars in gideon/.env:"
echo "  OPENWEATHERMAP_API_KEY"
