# Plan-State

A condition-aware activity orchestrator for personal life domains -- lawn care, gardening, hunting, health, home maintenance. It turns LLM-generated domain plans into managed tasks that automatically re-cascade when conditions change, activities complete, or dates slip.

Plan-state is a **capability** that registers into a running [Hermes Agent](https://github.com/NousResearch/hermes-agent) instance. It does not run standalone.

## How it works

1. **Plan**: Talk to Gideon (Hermes) via Telegram. Describe what you want to manage -- "help me plan my fall garden succession for Zone 7a." The LLM generates a structured domain plan and writes it to the plan store via MCP tools.

2. **Monitor**: Every morning at 6 AM, a deterministic cron job (zero LLM tokens) pulls weather, evaluates trigger conditions against current data, fires triggers when conditions are met, cascades dates through prep/follow-up chains, and syncs everything to Todoist.

3. **Brief**: At 6:15 AM, an LLM-backed cron job generates a concise morning briefing from the sync results and delivers it to Telegram.

4. **Act**: Tasks appear in Todoist with contextual descriptions and cascaded due dates. Complete them there; completions sync back to the plan store on the next morning run.

5. **Adapt**: When something changes, message Gideon. The LLM updates the plan store, and the next cron run re-cascades everything.

## Prerequisites

- A running Hermes Agent instance (the sibling `gideon/` repo handles this)
- Docker
- API keys: `OPENWEATHERMAP_API_KEY`, `TODOIST_API_KEY` (set in `gideon/.env`)

## Setup

```bash
# 1. Start the Hermes infrastructure
cd ../gideon
docker compose up -d

# 2. Register plan-state into the running instance
cd ../plan-state
./register.sh
```

`register.sh` copies skills and scripts, initializes the database, installs Python dependencies, and registers the MCP server and cron jobs. Re-run it after changing files in `skills/` or `scripts/`.

Files in `mcp-server/`, `sync/`, and the repo root (`schema.sql`, `init-db.py`) are volume-mounted into the container -- edits are live immediately without re-running `register.sh`.

## Verify

```bash
docker exec -it gideon-gateway hermes chat -q 'Use the plansync tools to list domains'
```

## What's built

- **SQLite plan store**: 7-table schema tracking domains, activities, steps, conditions, weather, Todoist sync state, and an activity log
- **MCP server**: 10 tools for reading and writing plan state (create/update/complete/defer activities, record observations, query upcoming items and weather)
- **Daily sync pipeline**: 7-step deterministic script -- weather pull, condition evaluation, trigger evaluation, date re-estimation, overdue check, Todoist sync, summary output
- **Morning briefing**: LLM-generated daily briefing from sync output
- **Registration script**: One-command install into a running Hermes instance

See [BUILD_PLAN.md](BUILD_PLAN.md) for current status and next steps.

## Product decisions

**Why Hermes Agent, not raw Claude sessions?** Persistent cross-session memory, a skill system, Telegram integration, and cron scheduling come built-in. No custom infrastructure to maintain.

**Why a deterministic cron pipeline?** Weather evaluation, trigger logic, date cascading, and Todoist sync are all rule-based. Running them without LLM involvement means zero token cost, zero latency, and zero external dependency beyond the weather and Todoist APIs. The LLM is reserved for where it adds value: planning conversations and contextual briefings.

**Why Todoist?** The user already lives in Todoist. Tasks appear there naturally alongside everything else, with cascaded due dates and contextual descriptions. No new app to check.

**Why SQLite?** Single-user system on a home server. No need for a database server process. WAL mode handles concurrent reads from MCP server and cron job.

**Why split repos?** Hermes infrastructure (`gideon/`) can be upgraded, reconfigured, or redeployed independently from this capability. Plan-state registers itself and doesn't care how Hermes is hosted.

## Architecture

```
User (Telegram)
    │
    ▼
Hermes Agent (Docker) ──── MCP ────► plan-state MCP server ──► SQLite DB
    │                                                              ▲
    │ cron 6:00 AM                                                 │
    ▼                                                              │
daily_sync.py ─── Weather API ──► condition eval ──► trigger ──► cascade
    │                                                              │
    │                                                              ▼
    └──────────────────────────────────────────────────────► Todoist API
    │
    │ cron 6:15 AM
    ▼
briefing-context.py ──► LLM ──► Telegram briefing
```

## Future direction

The PRD (`docs/prd.md`) describes a v2 architecture based on Holland's *Signals and Boundaries*: federated autonomous agents interacting through tagged signals across semi-permeable boundaries. The current v1 is a stepping stone -- validating the core product insight (LLM-contextual proactive notifications for condition-dependent activities) before building the full signal infrastructure.
