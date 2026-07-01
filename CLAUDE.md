<!-- If using multiple AI coding tools, symlink this to AGENTS.md: ln -s CLAUDE.md AGENTS.md -->

# Plan-State

## What this is
A condition-aware activity orchestrator for personal life domains (lawn care, gardening, hunting, health, home maintenance). It turns LLM-generated domain plans into managed, condition-aware tasks that re-cascade automatically when things slip, complete, or change. Deployed as a capability that registers into a running Hermes Agent instance (branded "Gideon") on a Mac Mini home server. Users interact via Telegram; tasks surface in Todoist. A daily cron pipeline (zero LLM tokens) pulls weather, evaluates triggers, cascades dates, and syncs to Todoist. An LLM morning briefing follows.

## Build protocol
- The build plan lives in BUILD_PLAN.md. Read it at the start of every session.
- Find the next step with status "not started." Build it.
- If the step has a Test field that is not "manual," write the test before writing the implementation. Build until the test passes.
- After building a step, present it to the user for evaluation. Do not proceed to the next step until the user confirms.
- When the user approves a step:
  1. Mark it "complete" in BUILD_PLAN.md
  2. Add any notes about what changed or was learned
  3. Write a regression test for the approved behavior (unless one already exists from the Test field). This catches breakage from later steps.
  4. Update this file (CLAUDE.md) if new conventions, patterns, or structural decisions emerged
- When the user requests changes to a step, make them and present again. Do not mark complete until approved.
- If a step reveals that the plan needs to change (new steps, reordering, removal), update BUILD_PLAN.md and confirm with the user before continuing.
- Run existing regression tests before starting each new step. If anything is broken, fix it before building new behavior.

## Tech stack
- **Language**: Python 3 (no type hints in existing code)
- **Database**: SQLite 3 with WAL mode, foreign keys enabled
- **MCP server**: `mcp>=1.0.0` (stdio JSON-RPC)
- **HTTP clients**: `requests` (weather API, Todoist API)
- **Todoist**: `todoist-api-python` (REST v2)
- **Weather**: OpenWeatherMap API (current + forecast)
- **Runtime**: Docker container running Hermes Agent, deployed on Mac Mini
- **Messaging**: Telegram (via Hermes gateway)
- **LLM**: Local model via Ollama (LAN machine) for automated tasks; cloud LLM for interactive sessions

## Project structure
```
plan-state/
├── register.sh                 # Installs app into running Hermes instance
├── schema.sql                  # SQLite schema (7 tables)
├── init-db.py                  # Database initializer
├── mcp-server/
│   ├── server.py               # MCP server (11 tools) over stdio JSON-RPC
│   └── requirements.txt        # mcp>=1.0.0
├── sync/
│   ├── daily_sync.py           # 7-step deterministic sync pipeline (~650 lines)
│   └── requirements.txt        # requests, todoist-api-python
├── scripts/                    # Cron wrappers (copied to Hermes data dir by register.sh)
│   ├── daily-sync.py           # Delegates to sync/daily_sync.py
│   ├── briefing-context.py     # Reads sync output + DB for LLM briefing
│   └── briefing-context.sh     # Shell wrapper for briefing-context.py
├── skills/                     # Hermes skills (copied to Hermes data dir by register.sh)
│   ├── plansync.md             # MCP tool workflow and trigger format reference
│   ├── plansync-briefing.md    # Morning briefing generation instructions
│   └── domain-authoring.md     # Guides LLM through domain planning conversation → load_domain
├── sync-output/                # Daily JSON summaries (runtime, gitignored)
└── docs/
    ├── STATUS.md               # Session-level state tracking
    ├── prd.md                  # Target v2 architecture (signals & boundaries)
    └── archive/
        └── v1-plan-sync-mvp-spec.md  # Original v1 spec (frozen)
```

**Sibling repo**: `../gideon/` contains Hermes infrastructure (docker-compose.yml, .env, config.yaml). Plan-state registers itself into Gideon via `register.sh`.

**Volume mounts**: `mcp-server/server.py`, `sync/daily_sync.py`, `schema.sql`, and `init-db.py` are volume-mounted into the container at `/opt/plansync/`. Edits to these are live immediately. Skills and scripts are *copied* by `register.sh` and require re-running it after changes.

## Conventions
- Database IDs are 12-char hex strings from `uuid4().hex[:12]`
- All DB connections use WAL mode and foreign keys (`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON`)
- JSON fields in SQLite are stored as TEXT, deserialized on read via `row_to_dict()`
- MCP tool responses are JSON wrapped in `types.TextContent`
- Trigger definitions are JSON objects with a `type` field: `calendar`, `condition`, `dependency`, `compound`
- The cron pipeline for the initial implementation is deterministic (zero LLM tokens). LLM reasoning happens only in Hermes sessions and the morning briefing
- Step dates cascade automatically from activity trigger dates (prep = trigger - lead_days, follow_up = trigger + lead_days)
- Activity log captures all state changes with source attribution (`cron`, `hermes`, `todoist_webhook`)

## Do not
- Do not use class components or ORM -- raw SQL via sqlite3, schemas in schema.sql
- Do not evaluate weather conditions or sync to Todoist during planning conversations -- the cron job handles that
- Do not delete and recreate activities to modify them -- use update_activity
- Do not add external service dependencies to the automated cron pipeline without asking the user first -- additional external API calls beyond weather and Todoist need to be evaluated
- Do not break the volume-mount contract: files at the repo root and in mcp-server/sync/ are mounted live; files in skills/scripts/ are copied by register.sh

## Decisions
- **Hermes Agent, not raw Claude sessions** -- persistent memory, skill system, Telegram integration, cron scheduling all come free
- **SQLite, not Postgres** -- single-user system on a home server, no need for a database server
- **Deterministic cron, not LLM-in-the-loop** -- weather eval, trigger logic, date cascading, Todoist sync are all rule-based. Zero tokens, zero latency, zero external dependency beyond APIs
- **Todoist as task surface** -- user already lives in Todoist; tasks appear there naturally
- **Local LLM for automated tasks** -- zero marginal cost, no external dependency for the morning briefing pipeline. Model is swappable via Hermes config.
- **Split repos (plan-state + gideon)** -- Hermes infrastructure can be upgraded independently from this capability

## Inconsistencies
None currently tracked.
