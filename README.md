# Plan-State

A condition-aware activity orchestrator for personal life domains -- lawn care, gardening, hunting, health, home maintenance. It turns LLM-generated domain plans into managed tasks that automatically re-cascade when conditions change, activities complete, or dates slip.

Plan-state is a **capability** that registers into a running [Hermes Agent](https://github.com/NousResearch/hermes-agent) instance. It does not run standalone.

## How it works

1. **Plan**: Talk to Reach (Hermes) via Telegram. Describe what you want to manage -- "help me plan my fall garden succession for Zone 7a." The LLM generates a structured domain plan and writes it to the plan store via MCP tools.

2. **Monitor**: Every morning at 6 AM, a deterministic cron job (zero LLM tokens) pulls weather, evaluates trigger conditions against current data, fires triggers when conditions are met, and cascades dates through prep/follow-up chains.

3. **Brief**: At 6:15 AM, an LLM-backed cron job generates a concise morning briefing from the sync results and delivers it to Telegram. At 5 PM, a deterministic evening nudge lists anything still open today (silent when nothing is due).

4. **Act**: Work from the briefing. When you finish something, tell Reach ("done with the fungicide") -- it marks the activity complete and cascades follow-ups immediately.

5. **Adapt**: When something changes, message Reach. The LLM updates the plan store, and the next cron run re-cascades everything.

## Prerequisites

- A running Hermes Agent instance (the sibling `reach/` repo handles this)
- Docker
- API keys: `OPENWEATHERMAP_API_KEY` (set in `reach/.env`)

## Setup

```bash
# 1. Start the Hermes infrastructure
cd ../reach
docker compose up -d

# 2. Register plan-state into the running instance
cd ../plan-state
./register.sh
```

`register.sh` copies scripts, initializes the database, installs Python dependencies, and registers cron jobs. The entire repo is volume-mounted into the container at `/opt/plansync/`:

- **Skills**: loaded via Hermes `external_dirs` (configured in Reach's `config.yaml`) — live edits
- **Scripts**: thin wrappers copied into `/opt/data/scripts/` (Hermes requires scripts within this directory). They delegate to volume-mounted code, so the actual logic is live-editable.
- **MCP server**: configured in Reach's `config.yaml` (`mcp_servers.plansync`) — live edits
- **Sync pipeline, schema, init**: accessed directly via the volume mount — live edits

Re-run `register.sh` after adding new script files, editing script wrappers, or adding new cron jobs.

## Verify

```bash
docker exec -it reach-gateway hermes chat -q 'Use the plansync tools to list domains'
```

## What's built

- **SQLite plan store**: domains, activities, steps, condition cache, weather log, and a source-attributed activity log
- **MCP server**: tools for reading and writing plan state (load/amend domains, update/complete/defer activities, record observations, query upcoming items and weather); shared by Hermes and Claude as peer agents, with writes attributed per client (see `docs/claude-setup.md`)
- **Daily sync pipeline**: deterministic script -- weather pull, condition evaluation, trigger evaluation, date re-estimation, overdue check, summary output
- **Morning briefing**: LLM-generated daily briefing from sync output (includes recent field observations)
- **Evening nudge**: deterministic reminder of anything still open today; silent on clear days
- **Dossier export**: per-domain markdown state files (`domains/{slug}/dossier.md`), regenerated daily, so sessions without MCP access can orient instantly
- **Registration script**: One-command install into a running Hermes instance

See [BUILD_PLAN.md](BUILD_PLAN.md) for current status and next steps.

## Product decisions

**Why Hermes Agent, not raw Claude sessions?** Persistent cross-session memory, a skill system, Telegram integration, and cron scheduling come built-in. No custom infrastructure to maintain.

**Why a deterministic cron pipeline?** Weather evaluation, trigger logic, and date cascading are all rule-based. Running them without LLM involvement means zero token cost, zero latency, and zero external dependency beyond the weather API. The LLM is reserved for where it adds value: planning conversations and contextual briefings. The local model is swappable via Hermes config -- the system is model-agnostic.

**Why Telegram as the only task surface?** Todoist integration was removed in 2026-07: it was ~300 lines of sync code plus the system's most fragile external dependency (its API sunset broke the pipeline once), and daily polling meant checkbox completions were only detected next-day anyway. Conversational completion is immediate, cascades follow-ups on the spot, and can capture field notes a checkbox never could.

**Why SQLite?** Single-user system on a home server. No need for a database server process.

**Why split repos?** Hermes infrastructure (`reach/`) can be upgraded, reconfigured, or redeployed independently from this capability. Plan-state registers itself and doesn't care how Hermes is hosted.

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
    │
    │ cron 6:15 AM
    ▼
briefing-context.py ──► LLM ──► Telegram briefing
    │
    │ cron 5:00 PM
    ▼
evening_nudge.py ──► "still open today" ──► Telegram (silent if clear)
```

## Future direction

v1 is the target architecture. A more elaborate v2 design (federated signal/boundary agents) is archived at `docs/archive/v2-signals-boundaries-prd.md` -- revisit only if a full season of operation surfaces a concrete limitation of the current model.
