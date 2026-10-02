# Plan-State

Condition-aware tasks for personal life domains — lawn, garden, hunting, home.....

You describe a season once as a reusable **path template**. Dispatch turns it into items with triggers (a date, the weather, another item finishing, or a mix). An hourly job pulls the forecast and fires what's due. Your agent (Claude Desktop, Cursor, or [Hermes](https://github.com/NousResearch/hermes-agent) on Telegram) lists items as `G1` / `L2` and closes them when you say "done G1".

```
You ──► agent (MCP) ──► dispatch ──► SQLite
                           ▲
              hourly eval ─┘  weather + triggers
```

## Requirements

- Python 3.10+ **or** Docker
- A free [OpenWeatherMap](https://home.openweathermap.org/users/sign_up) API key (new keys can take up to an hour to activate)
- An MCP client: Claude Desktop, Cursor, Hermes, etc

## 1. Install

**Docker** (keeps the database in a volume; recommended):

```bash
git clone https://github.com/michaelkerr/plan-state.git
cd plan-state
cp .env.sample .env          # fill in OWM_API_KEY and DISPATCH_LOCATION
docker compose up -d
docker compose exec dispatch dispatch doctor
```

`DISPATCH_LOCATION` is `City,ST,US` — e.g. `Nashville,TN,US`. Doctor should report the weather key, location, and three built-in templates. Warnings about "no items" and "no eval yet" are expected.

**Local** (no Docker):

```bash
git clone https://github.com/michaelkerr/plan-state.git
cd plan-state
python3 -m pip install -e ".[dev]"
cp .env.sample .env          # same two values; export them in your shell
set -a && source .env && set +a
dispatch init
dispatch doctor
```

The database defaults to `~/.plansync/dispatch.db`. Custom templates you save later live next to it in `~/.plansync/paths/`.

## 2. Connect an agent

Skills tell the agent how to talk. MCP gives it the tools. Both are required.

### Claude Desktop

**Docker:** compose already publishes MCP at `http://127.0.0.1:8082/sse`. Add this under Settings → Developer → Edit Config:

```json
{
  "mcpServers": {
    "dispatch": {
      "url": "http://127.0.0.1:8082/sse"
    }
  }
}
```

**Local install:**

```json
{
  "mcpServers": {
    "dispatch": {
      "command": "dispatch",
      "args": ["serve", "--stdio"],
      "env": {
        "OWM_API_KEY": "your-key",
        "DISPATCH_LOCATION": "Nashville,TN,US",
        "DISPATCH_CLIENT": "claude",
        "DISPATCH_EVAL_MINUTES": "60"
      }
    }
  }
}
```

Restart Claude Desktop. You should see `status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`, `undo`.

```bash
mkdir -p ~/.claude/skills
for s in dispatch plan-state path-authoring briefing; do
  ln -sfn "$(pwd)/skills/$s" ~/.claude/skills/$s
done
```

### Cursor

Skills load from `skills/` when this repo is the open workspace. Add the MCP server so the tools appear.

Put this in **`.cursor/mcp.json`** (project) or Cursor Settings → MCP.

**Docker** (after `docker compose up -d`):

```json
{
  "mcpServers": {
    "dispatch": {
      "url": "http://127.0.0.1:8082/sse"
    }
  }
}
```

**Local install:**

```json
{
  "mcpServers": {
    "dispatch": {
      "command": "dispatch",
      "args": ["serve", "--stdio"],
      "env": {
        "OWM_API_KEY": "your-key",
        "DISPATCH_LOCATION": "Nashville,TN,US",
        "DISPATCH_CLIENT": "cursor",
        "DISPATCH_EVAL_MINUTES": "60"
      }
    }
  }
}
```

Reload MCP in Cursor. Same eight tools as Claude.

### Hermes (Telegram)

See [hermes/README.md](hermes/README.md). Hermes cron drives eval, briefing, and the evening nudge; the built-in scheduler stays off.

## 3. Put a plan in

Talk to the agent:

- "Help me set up my fall garden" — instantiates a built-in **template** (`garden-fall`, `lawn-cool-season`, `hunting-bow`) with this season's dates and places. They are not hardcoded calendars.
- "Make a template for spring garlic" — writes a new path, then you instantiate it

Or from the CLI:

```bash
dispatch paths
dispatch check-path garden-fall \
  --param zone=7a \
  --param frost_date_fall=2026-10-20 \
  --param 'beds=[{"name":"Bed 1"}]'
dispatch instantiate garden-fall garden \
  --param zone=7a \
  --param frost_date_fall=2026-10-20 \
  --param 'beds=[{"name":"Bed 1"}]'
dispatch eval --location "$DISPATCH_LOCATION"
dispatch briefing
```

Reply "done G1" (or `dispatch done G1`) to close an item.

## How a day works

| When | What | Tokens |
|---|---|---|
| Every hour | Weather pull + trigger eval | none |
| Morning | Briefing with completion codes (`G1`, `L2`) | none (text is already written) |
| Evening | Nudge if anything is still due; silent if not | none |
| When you talk | Agent calls `done` / `skip` / `defer` / `note` | your chat |

Docker Compose runs the hourly eval inside the container (`DISPATCH_EVAL_MINUTES=60`). Hermes users turn that off and use cron instead.

## What's in the box

- **dispatch** — the only running service: SQLite store, eval, briefing, 8 MCP tools, CLI
- **plan-state** — library/CLI for domain context and reconcile (no server)
- **3 example path templates** — fall garden, cool-season lawn, bow hunting (params, not 2026 literals)
- **Skills** — domain setup, path authoring, completions by code, briefing

See [ARCHITECTURE.md](ARCHITECTURE.md) for the component map, [INTENTS.md](INTENTS.md) for the design, and [ROADMAP.md](ROADMAP.md) for what's next.

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

Push and pull-request runs the same suite on GitHub Actions (Python 3.10 and 3.12).

After code changes on Docker: `docker compose up -d --build`. The database volume is kept.
