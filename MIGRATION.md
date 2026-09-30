# Migration: Current PlanSync → Dispatch + Plan-State

This guide covers migrating from the current `reach-plansync` container
to the new dispatch system.  The approach is parallel-run: old and new
run side by side, then the old is shut down once the new proves itself.

## Prerequisites

- The current `reach-plansync` container is running and healthy
- You have access to the Mac Mini host and the `reach` compose project
- Your OpenWeatherMap API key (check `~/Projects/reach/.env` for `OWM_API_KEY`)

## Phase 1: Build and start the new container

### 1.1 Build the dispatch image

```bash
cd ~/Projects/plan-state
docker build -f Dockerfile.dispatch -t plansync-dispatch:latest .
```

### 1.2 Add to your Reach compose

Add the plansync service to `~/Projects/reach/docker-compose.yml` (or
use the provided `docker-compose.plansync.yaml` as an override file):

```yaml
services:
  # ... existing gateway, dashboard, etc. ...

  plansync-new:
    image: plansync-dispatch:latest
    container_name: reach-plansync-new
    restart: unless-stopped
    environment:
      - OWM_API_KEY=${OWM_API_KEY}
      - DISPATCH_LOCATION=${DISPATCH_LOCATION:-Murfreesboro,TN,US}
      - DISPATCH_DB=/data/dispatch.db
      - DISPATCH_CLIENT=hermes
    volumes:
      - plansync-new-data:/data
    networks:
      - infra
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8082/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  plansync-new-data:
```

Add `DISPATCH_LOCATION=Murfreesboro,TN,US` to `~/Projects/reach/.env`.

The new service publishes `127.0.0.1:8083` on the host. The old container keeps `127.0.0.1:8082`. Inside the Docker network the new service is still `http://plansync-new:8082`.

### 1.3 Start the new container alongside the old

```bash
cd ~/Projects/reach
docker compose up -d plansync-new
```

### 1.4 Verify health

```bash
# From the host (8083; 8082 is the old container):
curl -sf http://127.0.0.1:8083/health

# Or from inside the Docker network:
docker exec reach-gateway curl -sf http://plansync-new:8082/health
```

You should see the dispatch doctor output with all checks OK (except
"No eval has run yet" and "No items" which are expected).

## Phase 2: Initialize and populate

### 2.1 Initialize the DB

The DB is auto-initialized on first serve.  Verify:

```bash
docker exec reach-plansync-new dispatch doctor
```

### 2.2 Export from the old system (for reference)

```bash
cd ~/Projects/plan-state
python -m scripts.migrate_to_dispatch \
  --db ~/reach-data/plansync/plansync.db \
  --out ./migration-output
```

Review the output files.  These show what your old system has — use them
as reference when setting up paths, not as direct imports.

### 2.3 Instantiate paths for your domains

Instead of importing old data 1:1, start fresh with path templates.
This is the clean-break approach — old items had accumulated noise.

```bash
# Exec into the new container to run commands:
docker exec -it reach-plansync-new bash

# Inside the container:
dispatch paths   # see available templates

# Garden (adjust dates/params for your season)
dispatch instantiate garden-fall garden \
  --param zone=7a \
  --param frost_date_fall=2026-10-20 \
  --param 'beds=[{"name":"Bed 1","properties":{"sun":"full"}},{"name":"Bed 2","properties":{"sun":"partial"}},{"name":"Bed 3","properties":{"sun":"full"}}]'

# Lawn
dispatch instantiate lawn-cool-season lawn \
  --param zone=7a \
  --param lawn_sqft=8000

# Hunting
dispatch instantiate hunting-bow hunting \
  --param season_open=2026-10-01 \
  --param season_close=2027-01-15

# Verify
dispatch status
dispatch doctor
```

### 2.4 Run a test eval

```bash
docker exec reach-plansync-new dispatch eval --location "Murfreesboro,TN,US"
```

Check that weather was pulled and triggers evaluated.

### 2.5 Test briefing and nudge

```bash
# From host or gateway container:
curl -sf http://plansync-new:8082/api/briefing
curl -sf http://plansync-new:8082/api/nudge
```

## Phase 3: Switch Hermes to the new system

### 3.1 Add the new MCP server to Hermes config

Edit `~/reach-data/config.yaml` (the LIVE config, not the backup):

```yaml
mcp_servers:
  # Keep the old one temporarily:
  plansync:
    url: "http://reach-plansync:8082/sse"
  # Add the new one:
  dispatch:
    url: "http://plansync-new:8082/sse"
```

Restart the gateway to pick up the change:

```bash
cd ~/Projects/reach
docker compose restart gateway
```

Now Hermes has both tool sets.  Test the new tools via Telegram:
ask Reach to use the `dispatch:status` tool, or try "done G3" style
completions (the dispatch skill routes these to the `dispatch:done` tool).

### 3.2 Update skills

Replace the old skill references in `external_dirs`:

```yaml
skills:
  external_dirs:
    # REMOVE: - /opt/data/skills/plansync
    - /opt/projects/plan-state/skills    # new skills (dispatch, plan-state, briefing)
    - /opt/data/skills/vault             # keep vault
```

Or, if the `plan-state` repo is not volume-mounted into the gateway,
copy the skills:

```bash
cp -r ~/Projects/plan-state/skills/dispatch ~/reach-data/skills/
cp -r ~/Projects/plan-state/skills/plan-state ~/reach-data/skills/
cp -r ~/Projects/plan-state/skills/briefing ~/reach-data/skills/
```

Then point `external_dirs` at `~/reach-data/skills/`.

### 3.3 Replace cron jobs

List existing cron jobs:

```bash
docker exec reach-gateway hermes cron list
```

Delete the old plansync cron jobs (hourly sync, 6:15 briefing, 5 PM nudge).

Add new ones that hit the dispatch HTTP API:

```bash
# Hourly eval (weather + triggers)
docker exec reach-gateway hermes cron create \
  --schedule "0 * * * *" \
  --command 'curl -sf http://plansync-new:8082/api/eval' \
  --deliver none

# Morning briefing at 6:15 AM → Telegram
docker exec reach-gateway hermes cron create \
  --schedule "15 6 * * *" \
  --command 'curl -sf http://plansync-new:8082/api/briefing' \
  --deliver telegram

# Evening nudge at 5 PM → Telegram (silent when empty)
docker exec reach-gateway hermes cron create \
  --schedule "0 17 * * *" \
  --command 'curl -sf http://plansync-new:8082/api/nudge' \
  --deliver telegram
```

### 3.4 Run for a few days in parallel

Both containers stay up.  Replace the old plansync cron jobs with the
dispatch jobs in 3.3.  Do not leave both sets scheduled — that delivers
two Telegram briefings and two nudges.

**Check for:**
- Briefings arrive at 6:15 with the new format (includes completion codes)
- Nudges arrive at 5 PM with codes
- `done G3` completions work via Telegram
- `dispatch doctor` shows recent eval timestamps
- No "phantom open" items (the old system's main pain point)

## Phase 4: Wind down the old system

Once you trust the new system (give it at least 3-5 days):

### 4.1 Remove old MCP server from Hermes config

Edit `~/reach-data/config.yaml`:

```yaml
mcp_servers:
  # REMOVE the old entry:
  # plansync:
  #   url: "http://reach-plansync:8082/sse"

  # Rename new to plansync (so skills/tools keep the same namespace):
  plansync:
    url: "http://plansync-new:8082/sse"
```

### 4.2 Stop the old container

```bash
cd ~/Projects/reach
docker compose stop plansync
```

### 4.3 Rename the new container (optional)

Update `docker-compose.yml`: rename `plansync-new` to `plansync`,
update the container_name and volume name.

```bash
docker compose up -d plansync
docker compose restart gateway
```

### 4.4 Archive old data

```bash
# Archive the old DB (don't delete yet)
cp ~/reach-data/plansync/plansync.db \
   ~/reach-data/plansync/plansync.db.archived-$(date +%Y%m%d)

# Old domain defs, dossiers, sync-output are now dead weight
# Archive or delete at your leisure
```

### 4.5 Clean up docker-compose.yml

Remove the old `plansync` service definition and its volume.

## What you lose (and when it comes back)

| Capability | Status | When it returns |
|---|---|---|
| Claude Desktop MCP | Restored 2026-09-25 | `docker exec -i -e DISPATCH_CLIENT=claude reach-plansync-new dispatch serve --stdio` in claude_desktop_config.json |
| Dossier files | Gone by design | Use `dispatch status` or MCP `status` tool instead |
| 15 MCP tools | Replaced by 8 | `status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`, `undo` |
| Ad-hoc activities via `load_domain` | Replaced | Build a custom path with the path-authoring skill (`draft_path`), then `instantiate` |
| Sync-output JSON | Gone by design | DB is the only truth; briefing reads it directly |
| Activity/step dual state machine | Simplified | Items + optional checklists; no separate step lifecycle |

## Rollback

If anything goes wrong during migration:

1. Stop the new container: `docker compose stop plansync-new`
2. Restore old MCP config in `~/reach-data/config.yaml`
3. Restore old skill `external_dirs`
4. Re-create old cron jobs
5. Restart gateway: `docker compose restart gateway`

The old system was never modified — it's still there, data intact.
