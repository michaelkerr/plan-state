# Migrating from the old plansync container

The `plansync/`, `mcp-server/`, and `sync/` packages are gone. Do not import the old SQLite 1:1 — instantiate this season from path templates instead.

## Point Hermes at dispatch

MCP:

```yaml
mcp_servers:
  dispatch:
    url: "http://dispatch:8082/sse"   # alias on plansync-new; or http://plansync-new:8082/sse
    transport: sse
    enabled: true
```

Cron (eval / briefing / nudge) should curl `http://dispatch:8082/api/...`. Stop the old `plansync` cron jobs so you do not get two Telegram messages.

Skills: `external_dirs` → this repo's `skills/` (dispatch, plan-state, path-authoring, briefing).

## Instantiate this season

```bash
docker exec -it reach-plansync-new dispatch paths

dispatch instantiate garden-fall garden \
  --param zone=7a \
  --param frost_date_fall=2026-10-20 \
  --param 'beds=[{"name":"Bed 1"}]'

dispatch instantiate lawn-cool-season lawn \
  --param zone=7a \
  --param lawn_sqft=8000 \
  --param spring_window=2026-02-15 \
  --param overseed_window=2026-08-15

dispatch instantiate hunting-bow hunting \
  --param season_open=2026-10-01 \
  --param season_close=2027-01-15

dispatch eval --location "$DISPATCH_LOCATION"
dispatch doctor
```

A plan the three built-ins do not cover is a new custom path (`draft_path` / path-authoring skill), then `instantiate`.

## Wind down the old container

Once briefings, codes (`done G1`), and eval look right: disable the old `plansync` MCP entry, `docker compose stop plansync`, and archive `plansync.db`. Leave the volume until you are sure.

Rollback is the reverse: stop dispatch, restore the old MCP/cron/skills, restart the gateway. The old DB was never rewritten.
