# Hermes install

Use this when Telegram (via [Hermes](https://github.com/NousResearch/hermes-agent)) is the daily surface. The dispatch container shares Hermes' Docker network. Hermes cron curls the HTTP API; Hermes talks MCP over SSE.

Hermes cron owns the hourly eval, so the built-in scheduler stays off (`DISPATCH_EVAL_MINUTES=0`).

## 1. Build the image

From the plan-state repo:

```bash
docker build -t plan-state-dispatch:latest .
```

## 2. Add the service to Hermes compose

Copy the service from `docker-compose.override.yaml` into your Hermes compose file, or merge the override:

```bash
docker compose -f /path/to/hermes/docker-compose.yml \
  -f /path/to/plan-state/hermes/docker-compose.override.yaml \
  up -d dispatch
```

Required env (in the Hermes `.env`):

```
OWM_API_KEY=...                 # or OPENWEATHERMAP_API_KEY if you already have it
DISPATCH_LOCATION=Nashville,TN,US
```

The service is named `dispatch` so cron and skills can reach `http://dispatch:8082`.

## 3. Point Hermes at it

In the live Hermes `config.yaml`:

```yaml
mcp_servers:
  dispatch:
    url: "http://dispatch:8082/sse"
    transport: sse
    enabled: true

skills:
  external_dirs:
    - /opt/projects/plan-state/skills    # or copy skills/ into Hermes' skills dir
```

Restart the gateway so it picks up the MCP server.

## 4. Register cron

Hermes needs the scripts on a path it can execute. Copy them, then create the jobs:

```bash
cp hermes/cron/dispatch-*.sh "$REACH_DATA_PATH/scripts/"

# Hourly eval (weather + triggers)
hermes cron create --schedule "0 * * * *" \
  --command 'curl -sf http://dispatch:8082/api/eval' \
  --deliver none

# Morning briefing at 6:15 → Telegram
hermes cron create --schedule "15 6 * * *" \
  --command 'curl -sf http://dispatch:8082/api/briefing' \
  --deliver telegram

# Evening nudge at 5 PM → Telegram (silent when empty)
hermes cron create --schedule "0 17 * * *" \
  --command 'curl -sf http://dispatch:8082/api/nudge' \
  --deliver telegram
```

`dispatch doctor` (inside the container) should then show a recent eval after the first hour.

## 5. First plan

Ask Hermes on Telegram: "help me set up my fall garden". The plan-state skill walks the params and calls `instantiate`. For a plan no built-in covers, the path-authoring skill drafts a template first.

Coming from the old plansync container? See [docs/migrating-from-plansync.md](../docs/migrating-from-plansync.md).
