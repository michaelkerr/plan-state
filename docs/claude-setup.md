# Registering plansync in Claude desktop

Claude gets the same MCP tools Hermes has — same server, same database, all
writes stay container-side. Client identity defaults to `hermes` for all
SSE connections (the `PLANSYNC_CLIENT` env var is set in the container's
environment, not per-connection).

## Claude desktop config

The plansync MCP server runs in the `reach-plansync` container, exposing
an SSE endpoint on port 8082 (mapped to the host at `127.0.0.1:8082`).
Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "plansync": {
      "url": "http://localhost:8082/sse"
    }
  }
}
```

## Verifying

1. Claude desktop → tools list shows the plansync tools.
2. Test with any read tool (e.g. `get_domains`).
3. Health check from the terminal:

```
curl http://localhost:8082/health
```

## Rebuilding after code changes

Code is baked into the container image at build time (not volume-mounted).
After editing plan-state code, rebuild and restart:

```
cd ../reach
docker compose build plansync
docker compose up -d plansync
```

The container health check (`/health`) confirms the server is running and
the DB is reachable. Claude Desktop reconnects automatically on restart.
