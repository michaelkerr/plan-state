<!-- If using multiple AI coding tools, symlink this to AGENTS.md: ln -s CLAUDE.md AGENTS.md -->

# Plan-State

## What this is
A condition-aware activity orchestrator for personal life domains (lawn care, gardening, hunting, health, home maintenance). It turns LLM-generated domain plans into managed, condition-aware tasks that re-cascade automatically when things slip, complete, or change. Deployed as a capability that registers into a running Hermes Agent instance (branded "Gideon") on a Mac Mini home server. Telegram is the sole task surface: a daily cron pipeline (zero LLM tokens) pulls weather, evaluates triggers, and cascades dates; an LLM morning briefing follows at 6:15, and a deterministic evening nudge at 5 PM lists anything still open (silent on clear days). Completions are conversational -- the user tells Gideon, which calls complete_activity.

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
- **Database**: SQLite 3, WAL journal mode, lives at `/opt/data/plansync/plansync.db` (APFS-backed Hermes data dir -- NEVER on the exFAT/VirtioFS repo mount, where WAL fails), foreign keys enabled
- **MCP server**: `mcp>=1.0.0` (stdio JSON-RPC)
- **HTTP clients**: `requests` (weather API)
- **Weather**: OpenWeatherMap API (current + forecast)
- **Runtime**: Docker container running Hermes Agent, deployed on Mac Mini
- **Messaging**: Telegram (via Hermes gateway)
- **LLM**: Local model via Ollama (LAN machine) for automated tasks; cloud LLM for interactive sessions

## Project structure
```
plan-state/
├── register.sh                 # Installs app into running Hermes instance
├── schema.sql                  # SQLite schema (6 tables)
├── init-db.py                  # Database initializer
├── plansync/
│   └── engine.py               # Shared engine: get_db, log_change, cascade, trigger/step date math
├── mcp-server/
│   ├── server.py               # MCP server (10 tools) over stdio JSON-RPC
│   └── requirements.txt        # mcp>=1.0.0
├── sync/
│   ├── daily_sync.py           # Deterministic sync pipeline (weather, conditions, triggers, cascade, overdue)
│   ├── evening_nudge.py        # Evening "still open today" reminder (silent when clear)
│   └── requirements.txt        # requests
├── scripts/                    # Cron wrappers (copied to Hermes data dir by register.sh)
│   ├── daily-sync.py           # Delegates to sync/daily_sync.py
│   ├── briefing-context.py     # Reads sync output + DB for LLM briefing
│   ├── briefing-context.sh     # Shell wrapper for briefing-context.py
│   └── evening-nudge.py        # Delegates to sync/evening_nudge.py
├── skills/                     # Hermes skills (loaded via external_dirs, live immediately)
│   ├── plansync.md             # MCP tool workflow and trigger format reference
│   ├── plansync-briefing.md    # Morning briefing generation instructions
│   └── domain-authoring.md     # Guides LLM through domain planning conversation → load_domain
├── sync-output/                # Daily JSON summaries (runtime, gitignored)
└── docs/
    ├── STATUS.md               # Session-level state tracking
    └── archive/
        ├── v1-plan-sync-mvp-spec.md       # Original v1 spec (frozen)
        └── v2-signals-boundaries-prd.md   # Shelved v2 architecture (archived 2026-07-19; revisit only if a full season surfaces a concrete v1 limitation)
```

**Sibling repo**: `../gideon/` contains Hermes infrastructure (docker-compose.yml, .env). Plan-state registers itself into Gideon via `register.sh`. The LIVE Gideon config.yaml and data dir are at `$GIDEON_DATA_PATH` (/Users/michaelkerr/gideon-data, mounted at /opt/data) -- `../gideon/data/` is only the nightly backup target (mounted at /opt/data-backup); editing config there does nothing.

**Volume mounts**: The entire plan-state repo is volume-mounted into the container at `/opt/plansync/`. Skills are loaded via Hermes `external_dirs` (live edits). MCP server and sync code are accessed directly via the mount (live edits). Scripts are thin wrappers copied by `register.sh` — they delegate to the volume-mounted code, so the actual logic is still live-editable. The MCP server is configured in Gideon's `config.yaml`; `register.sh` handles one-time setup (DB init, pip deps, cron registration) plus script copying.

## Conventions
- Database IDs are 12-char hex strings from `uuid4().hex[:12]`
- All DB connections go through `engine.get_db()` (`busy_timeout=5000`, `foreign_keys=ON`). Journal mode is a persistent DB property set at init/migration: WAL at the APFS location. Never create or move the DB onto the exFAT/VirtioFS mount (WAL breaks there, see 2026-07-11 incident)
- JSON fields in SQLite are stored as TEXT, deserialized on read via `row_to_dict()`
- MCP tool responses are JSON wrapped in `types.TextContent`
- Trigger definitions are JSON objects with a `type` field: `calendar`, `condition`, `dependency`, `compound`
- The cron pipeline for the initial implementation is deterministic (zero LLM tokens). LLM reasoning happens only in Hermes sessions and the morning briefing
- Step dates cascade automatically from activity trigger dates (prep = trigger - lead_days, follow_up = trigger + lead_days)
- Activity log captures all state changes with source attribution (`cron`, `hermes`)
- Activities carry an optional free-form `group_name` for within-domain bundling (crop, bed, species). Display/organization only -- trigger logic comes from dependency chains, never groups
- A domain = one location/weather context. Activity vs step: needs its own trigger (date, weather, dependency) → activity; fixed-offset chore around a triggered event → step
- weather_log holds ONE row per location per local day, enforced by `UNIQUE(location, weather_date)` -- the upsert is `INSERT ... ON CONFLICT DO UPDATE`, so ad-hoc manual sync runs refresh rather than duplicate. Daily high/low are derived from the 3-hourly forecast via derive_daily_range(), not the snapshot
- Conditions rows are DERIVED from trigger_def condition leaves at load/update time (engine.derive_conditions); definitions with an explicit `conditions` array are rejected. The conditions table is an evaluation cache (is_met/current_value), never authored directly
- One authoring path: load_domain (new domain) / add_activities (grow a domain, including single activities); one modification path: update_activity / complete_activity / defer_activity. The single-shot create_domain and create_activity tools were removed (Step 22)
- Deferral is a date move, not a status: defer_activity requires new_date, rewrites trigger_def via engine.defer_trigger_def (calendar date moved, compound calendar leg moved, condition/dependency wrapped with an earliest-date gate), and returns the activity to 'watching' so the cron re-fires it. There is no 'deferred' status
- No recurrence, no step conditions, no soil_temp -- all were write-only surface; validation rejects them with actionable errors. Valid condition metrics: daily_high, daily_low, temp_high, temp_low (unknown metrics rejected)
- Shared logic lives in `plansync/engine.py` (get_db, log_change, cascade_step_dates, compute_trigger_date, step_due_date, row_to_dict); server.py, daily_sync.py, and evening_nudge.py import it and must not define local copies (enforced by tests/test_engine_extraction.py). DB path and client identity resolve from env (`PLANSYNC_DB`, `PLANSYNC_CLIENT`) at call time
- activity_log source attribution: `cron` (sync pipeline, passed explicitly), `hermes`/`claude` (via PLANSYNC_CLIENT env on the MCP server), `human` (reserved)

## Do not
- Do not use class components or ORM -- raw SQL via sqlite3, schemas in schema.sql
- Do not evaluate weather conditions during planning conversations -- the cron job handles that
- Do not delete and recreate activities to modify them -- use update_activity
- Do not add external service dependencies to the automated cron pipeline without asking the user first -- additional external API calls beyond weather need to be evaluated
- Do not break the volume-mount contract: the entire repo is mounted at /opt/plansync/; skills are loaded via external_dirs, scripts are copied (Hermes blocks symlinks outside /opt/data/scripts/), MCP server config lives in Gideon's config.yaml

## Decisions
- **Hermes Agent, not raw Claude sessions** -- persistent memory, skill system, Telegram integration, cron scheduling all come free
- **SQLite, not Postgres** -- single-user system on a home server, no need for a database server
- **Deterministic cron, not LLM-in-the-loop** -- weather eval, trigger logic, date cascading are all rule-based. Zero tokens, zero latency, zero external dependency beyond the weather API
- **Telegram as sole task surface (2026-07-19)** -- Todoist integration removed: ~300 lines + the system's most fragile external dependency (API sunset incident) for a once-daily completion poll. Completions are conversational via complete_activity (immediate, captures notes); the evening nudge replaces due-time reminders
- **Local LLM for automated tasks** -- zero marginal cost, no external dependency for the morning briefing pipeline. Model is swappable via Hermes config.
- **Split repos (plan-state + gideon)** -- Hermes infrastructure can be upgraded independently from this capability

## Inconsistencies
None currently tracked.
