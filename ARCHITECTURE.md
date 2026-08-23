# Architecture

## System overview

PlanSync is a SQLite-backed plan store with three consumers: an MCP server (interactive tools for Hermes and Claude), a cron pipeline (deterministic hourly evaluation), and a set of Telegram surfaces (morning briefing, evening nudge). All three import shared logic from a single engine module; all three read and write the same database. The system runs inside a Docker container (Hermes Agent / Reach) on a Mac Mini.

## Component map

### plansync/engine.py — shared engine

- **Purpose**: Single source of truth for DB access, state machines, cascade logic, and view queries. Every status change, date cascade, and log entry flows through here.
- **Entry point**: imported by server.py, sync_pipeline.py, evening_nudge.py, briefing_context.py, export_dossier.py
- **Depends on**: sqlite3, the schema (views defined in schema.sql)
- **Depended on by**: everything
- **Key patterns**:
  - `get_db()` / `connect()` — all DB connections; sets busy_timeout and foreign_keys. `connect()` is a context manager for automatic cleanup
  - `new_id()` / `new_batch_id()` — 12-char hex IDs from uuid4
  - `transition(conn, entity_type, entity_id, event, context)` — validates against ACTIVITY_TRANSITIONS / STEP_TRANSITIONS tables, applies the status change, returns side-effect events
  - `react(conn, events, batch_id)` — processes side effects: auto-completes prep steps, promotes follow-ups, fires dependency triggers. Each produces further transitions
  - `cascade_step_dates()` — re-derives step due dates from an activity's trigger_date
  - `log_change()` — writes to activity_log with source attribution and optional batch_id
  - `get_actionable_items()` / `get_open_activities()` — query the SQL views with optional filters

### plansync/authoring.py — plan authoring logic

- **Purpose**: Validation, insertion, sync, and ref resolution for domain definitions. Extracted from server.py so the logic is shared and testable without MCP.
- **Entry point**: imported by server.py
- **Depends on**: engine.py
- **Depended on by**: server.py
- **Key patterns**:
  - Functions return plain data (dicts/lists) and raise ValueError on failures; callers wrap in ok()/err()
  - `validate_domain_definition()` / `validate_activities()` — structural validation with path-annotated errors
  - `insert_activity()` — creates one activity with steps and derived conditions
  - `sync_domain()` — diffs a declaration against DB state (matched by ref_name → name → auto-slug), applies changes or returns dry-run report
  - `resolve_refs()` — converts activity_ref names to activity_id in trigger_defs

### mcp-server/server.py — MCP tool server

- **Purpose**: Exposes the plan store as 15 typed tools over stdio JSON-RPC. Both Hermes (Telegram) and Claude connect as clients.
- **Entry point**: `server.py` (run as a subprocess by each MCP client)
- **Depends on**: engine.py, authoring.py, `mcp` library
- **Depended on by**: Hermes Agent (config.yaml), Claude (claude_desktop_config.json via docker exec)
- **Key patterns**:
  - One function per tool (`_complete_activity`, `_load_domain`, etc.), dispatched by `call_tool()`
  - All status changes go through `transition()` + `react()`
  - `ok()` / `err()` wrap data into `CallToolResult` with `isError` flag for proper MCP error signaling
  - Each tool call uses `with connect() as conn:` for automatic connection cleanup

### sync/sync_pipeline.py — hourly cron pipeline

- **Purpose**: Deterministic (zero LLM tokens) evaluation loop. Pulls weather, evaluates conditions, fires triggers, cascades dates, checks overdue.
- **Entry point**: `main()`, called by scripts/sync.py wrapper
- **Depends on**: engine.py, `requests` (weather API), OpenWeatherMap
- **Depended on by**: cron (hourly), briefing_context.py (reads its JSON output)
- **Key patterns**:
  - Five independent stages, each callable alone: `pull_weather()`, `evaluate_conditions()`, `evaluate_triggers()`, `cascade_dates()`, `check_overdue()`
  - Each stage returns an explicit result dict and optionally feeds a `SyncSummary`
  - `save_output()` writes/merges a daily JSON file (event lists accumulate across hourly runs, state snapshots replace)
  - Trigger evaluation uses the same `transition()` path as the MCP server
  - Weather: one row per location per day via upsert; daily high/low derived from 3-hourly forecast

### sync/briefing_context.py — morning briefing data

- **Purpose**: Reads sync output and DB state into structured sections for the LLM morning briefing.
- **Entry point**: `main()`, called by scripts/briefing-context.py → briefing-context.sh
- **Depends on**: engine.py (get_db, get_actionable_items, get_open_activities)
- **Depended on by**: the morning-briefing cron job (6:15 AM, Telegram delivery via LLM skill)
- **Key patterns**:
  - "Due Today" comes from the shared view layer (same definition as nudge and MCP server)
  - "Fired Since Yesterday" queries activity_log for trigger_fire entries in the last 24h (DB is source of truth, not the daily JSON which resets at midnight)

### sync/evening_nudge.py — evening reminder

- **Purpose**: Lists anything still open as of today. Silent when nothing is due.
- **Entry point**: `build_nudge(conn, today)`, called by scripts/evening-nudge.py
- **Depends on**: engine.py (get_actionable_items, get_open_activities)
- **Depended on by**: cron (5 PM, Telegram delivery, no LLM)
- **Key patterns**: Deterministic; empty output = no Telegram message

### sync/export_dossier.py — per-domain markdown state files

- **Purpose**: Generates a human-readable snapshot of each domain's plan state, so sessions without MCP access can orient instantly.
- **Entry point**: `main()`, runs after sync_pipeline in the hourly cron
- **Depends on**: engine.py, rotation configs (JSON) in the domain directory
- **Output**: `domains/{slug}/dossier.md` under PLANSYNC_DOMAINS_DIR

### sync/export_domain_json.py — domain JSON export

- **Purpose**: Exports a domain from the DB as a clean, re-importable JSON definition (the format load_domain accepts).
- **Depends on**: engine.py

### schema.sql — database schema

- **Purpose**: Defines all tables, indexes, and views. Single source of truth; migrations extract DDL from here.
- **Tables**: domains, activities, steps, conditions, weather_log, activity_log
- **Views**: open_steps (base), actionable_items (due now), open_activities (not completed/skipped)

## Data flow

### Hourly sync (cron, zero tokens)

1. **pull_weather**: GET OpenWeatherMap current + forecast → upsert one weather_log row per location per day (high/low derived from 3-hourly forecast)
2. **evaluate_conditions**: read weather_log → update conditions.is_met / .current_value for all watching activities
3. **evaluate_triggers**: for each watching activity, check if trigger_def is satisfied → transition(trigger_fire) → cascade step dates
4. **cascade_dates**: for condition-type triggers, estimate trigger_date from forecast → cascade step dates if moved
5. **check_overdue**: find steps past due_date still in 'pending' → transition(overdue) to promote to 'due'
6. **save_output**: merge results into daily JSON (accumulate events, replace snapshots)
7. **export_dossier**: render each domain's plan state to markdown

### Activity completion (interactive, via MCP)

1. User tells Hermes/Claude "done with X"
2. Agent calls `complete_activity(activity_id, notes)`
3. `transition(activity, complete)` → status 'completed', returns events
4. `react(events)` processes cascade: auto-completes open prep steps, promotes follow-up steps to 'due', fires dependency triggers on waiting activities
5. All changes logged under one batch_id (undoable)

### Undo

1. Agent calls `undo()` (most recent batch) or `undo(item_type, item_id)` (most recent batch touching that item)
2. Walk batch entries in reverse order: `transition(revert, to_status=logged_prior_status)` for each status change, restore logged field values for date cascades and manual updates
3. Undo of an undo is refused (the finder skips any batch containing an action='undo' entry)

### Domain authoring (interactive, via MCP)

1. User has a planning conversation with Hermes or Claude (guided by the domain-authoring skill)
2. Agent calls `load_domain(definition)` with a structured JSON definition
3. If the domain is new: validate, create domain + activities + steps + conditions atomically
4. If the domain exists: sync mode — diff declaration against DB state (matched by ref_name → name → auto-slug), create new activities, update changed ones, flag missing ones (never auto-delete)

## Data model

- **domain** has many **activities**; an activity has many **steps** and many derived **conditions**
- Activities have a `ref_name` (stable slug, immutable after creation) for matching across renames
- Steps are typed as `prep` (before trigger) or `follow_up` (after trigger); due_date is derived from the parent's trigger_date ± lead_days
- Conditions are derived from condition-type leaves in trigger_def and are never authored directly — the conditions table is an evaluation cache
- `activity_log` records every change with source attribution (cron/hermes/claude) and batch_id for grouping
- `weather_log` holds one row per location per local day

## Integration points

- **OpenWeatherMap API** (current + 5-day/3-hour forecast): called once per location per sync run. If the API is down, later stages still run from existing weather_log data.
- **Hermes Agent** (MCP client): connects to server.py as a subprocess, configured in Reach's config.yaml
- **Claude** (MCP client): connects to server.py via `docker exec` into the running container
- **Telegram** (via Hermes gateway): delivery surface for briefing and nudge cron jobs

## Deployment topology

```
Mac Mini (host)
├── reach-data/ ($REACH_DATA_PATH, backed up nightly)
│   └── plansync/
│       ├── plansync.db          (SQLite, WAL, APFS-backed)
│       ├── domains/{slug}/      (dossiers, rotation config, reference docs)
│       └── sync-output/         (daily JSON from sync pipeline)
├── plan-state/  (this repo, volume-mounted at /opt/plansync/)
└── reach/       (sibling repo: docker-compose.yml, .env)

Docker (reach-gateway container)
├── /opt/plansync/       ← volume mount of plan-state repo (live edits)
├── /opt/data/plansync/  ← volume mount of reach-data/plansync/ (DB + data)
├── /opt/data/scripts/   ← copied thin wrappers (register.sh puts them here)
└── Hermes Agent         ← loads skills via external_dirs, runs MCP + cron
```
