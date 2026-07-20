# Registering plansync in Claude desktop

Claude gets the same MCP tools Hermes has — same server, same database, all
writes stay container-side. Client identity flows through the `PLANSYNC_CLIENT`
env var, so `activity_log.source` records which agent made each change
(`hermes` is the default; Claude's config sets `claude`).

## One-time DB migration

The live database was created with the old `source IN ('cron','hermes')`
constraint, which SQLite enforces from the table's stored DDL — writes with
`source='claude'` fail until the table is rebuilt. Run once on the Mac Mini:

```
docker exec -i gideon-gateway python3 /opt/plansync/scripts/migrate-source-enum.py
```

Idempotent; safe to re-run. New databases created from `schema.sql` don't need it.

## Claude desktop config

Claude desktop launches the server inside the running Gideon container via
`docker exec`. On the Mac Mini itself, add to `claude_desktop_config.json`
(Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "plansync": {
      "command": "docker",
      "args": [
        "exec", "-i",
        "-e", "PLANSYNC_CLIENT=claude",
        "gideon-gateway",
        "python3", "/opt/plansync/mcp-server/server.py"
      ]
    }
  }
}
```

From another machine on the LAN, prefix with ssh (requires key-based auth to
the Mac Mini):

```json
{
  "mcpServers": {
    "plansync": {
      "command": "ssh",
      "args": [
        "macmini",
        "docker", "exec", "-i",
        "-e", "PLANSYNC_CLIENT=claude",
        "gideon-gateway",
        "python3", "/opt/plansync/mcp-server/server.py"
      ]
    }
  }
}
```

The server process starts per session and exits when the session closes —
fine for interactive use. If startup latency ever matters, a persistent stdio
wrapper is a small addition.

## Verifying

1. Claude desktop → tools list shows the plansync tools.
2. Make any write from Claude (e.g. `add_observation`), then check attribution:

```
docker exec -i gideon-gateway sqlite3 /opt/plansync/plansync.db \
  "SELECT timestamp, item_type, action, source FROM activity_log ORDER BY id DESC LIMIT 5;"
```

The new row shows `source=claude`; Hermes and cron writes continue to show
`hermes` / `cron`.
