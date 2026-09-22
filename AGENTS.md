<!-- If using multiple AI coding tools, symlink this to AGENTS.md: ln -s CLAUDE.md AGENTS.md -->

# Plan-State

## What this is
A condition-aware activity orchestrator for personal life domains (lawn care, gardening, hunting). It turns LLM-generated domain plans into managed, condition-aware tasks that re-cascade automatically when things slip, complete, or change. Deployed as a capability that registers into a running Hermes Agent instance (branded "Reach") on a Mac Mini home server. Telegram is the sole task surface: an hourly cron pipeline (zero LLM tokens, local delivery) pulls weather, evaluates triggers, and cascades dates; an LLM morning briefing at 6:15 reads the 6:00 run's output, and a deterministic evening nudge at 5 PM lists anything still open (silent on clear days). Completions are conversational -- the user tells Reach (Telegram) or Claude, which calls complete_activity. Hermes and Claude are peer agents of the same engine: both use the same MCP server and authoring skill, with writes distinguished by source attribution (docs/claude-setup.md covers the Claude side). Per-domain dossier files (`/opt/data/plansync/domains/{slug}/dossier.md`, regenerated hourly) orient sessions without MCP access.

**Repo = code, reach-data = state.** This repo contains only source: engine, MCP server, sync pipeline, skills, schema, tests. All data — the DB, domain definitions, dossiers, reference docs, rotation configs, sync output — lives under `/opt/data/plansync/` (host: `$REACH_DATA_PATH/plansync/`, backed up nightly). Never commit domain data or runtime output to this repo.

## Work protocol
- The roadmap lives in ROADMAP.md. Read it at the start of every session.
- Pick a NOW item to work on. Items are not sequenced -- choose based on what is most needed.
- Before starting work on a NOW item:
  1. Run the full test suite. Fix anything broken before adding new work.
  2. Read the item's "Touches" field. Review those parts of the codebase to understand current state.
  3. Check DECISIONS.md for prior decisions that affect this work.
- While working:
  1. Write or update tests for any behavior you change or add.
  2. Follow the conventions below. If a situation is not covered, check how similar cases are handled elsewhere in the codebase and follow that pattern. If it is genuinely new, document the convention you choose.
  3. If work reveals a new risk, update the item's Risk field.
  4. If work uncovers tech debt or a bug unrelated to the current item, add it to ROADMAP.md in the appropriate bucket. Do not fix it now unless it blocks the current work.
- When work is done:
  1. Update ROADMAP.md: remove the item from NOW, update "What's built" if the product's capabilities changed.
  2. Promote an item from Next to NOW if the NOW bucket is thin.
  3. Update CLAUDE.md if new conventions or patterns emerged.
  4. Update ARCHITECTURE.md if the system's structure changed.
  5. Log any significant decisions in DECISIONS.md.
- When the user starts a new session, read CLAUDE.md, ROADMAP.md, and ARCHITECTURE.md before beginning work.

## Tech stack
- **Language**: Python 3 (no type hints in existing code)
- **Database**: SQLite 3, WAL journal mode, lives at `/opt/data/plansync/plansync.db` (APFS-backed Hermes data dir -- NEVER on the exFAT/VirtioFS repo mount, where WAL fails), foreign keys enabled
- **MCP server**: `mcp>=1.0.0` (stdio JSON-RPC)
- **HTTP clients**: `requests` (weather API)
- **Weather**: OpenWeatherMap API (current + forecast)
- **Runtime**: Docker container running Hermes Agent, deployed on Mac Mini
- **Messaging**: Telegram (via Hermes gateway)
- **LLM**: Local model via Ollama (LAN machine) for automated tasks; cloud LLM for interactive sessions

## Architecture overview
Three-layer architecture: a shared engine (plansync/engine.py) for DB access, state machines, and cascade logic; an MCP server (mcp-server/server.py) for interactive tools; and a sync pipeline (sync/) for deterministic cron evaluation. All three read/write the same SQLite database. See ARCHITECTURE.md for the component map, data flow, and deployment topology.

## Project structure
```
plan-state/
├── register.sh                 # Installs app into running Hermes instance
├── schema.sql                  # SQLite schema (tables, indexes, views)
├── init-db.py                  # Database initializer
├── ROADMAP.md                  # Priority-bucketed work management
├── ARCHITECTURE.md             # Component map, data flow, deployment topology
├── DECISIONS.md                # Architectural decision log
├── pyproject.toml              # Package config: plansync installable, pytest pythonpath
├── plansync/
│   ├── engine.py               # Shared engine: DB access, state machines, cascade, view queries
│   └── authoring.py            # Plan authoring: validation, insertion, sync, ref resolution
├── mcp-server/
│   ├── server.py               # MCP server: 15 tools over SSE (Starlette + uvicorn)
│   └── requirements.txt        # mcp>=1.0.0
├── sync/
│   ├── sync_pipeline.py        # Hourly deterministic pipeline (5 independent stages)
│   ├── morning_briefing.py     # 6:15 AM deterministic briefing (today/overdue/week/conditions/weather)
│   ├── evening_nudge.py        # 5 PM "still open today" (silent when clear)
│   ├── briefing_context.py     # Older LLM-mediated briefing (replaced by morning_briefing.py)
│   ├── export_dossier.py       # Per-domain markdown state files
│   ├── export_domain_json.py   # DB → re-importable domain JSON
│   └── requirements.txt        # requests
├── scripts/                    # Cron wrappers (copied into container by register.sh)
│   ├── sync.py                 # Delegates to sync_pipeline.py + export_dossier.py
│   ├── briefing-context.py     # Delegates to briefing_context.py
│   ├── briefing-context.sh     # Shell wrapper for briefing-context.py
│   ├── evening-nudge.py        # Delegates to evening_nudge.py
│   └── migrate-*.py            # One-time DB migrations (historical; already applied)
├── skills/                     # Hermes skills (loaded via external_dirs, live immediately)
│   ├── plansync.md             # MCP tool workflow and trigger format reference
│   ├── plansync-briefing.md    # Morning briefing generation instructions
│   └── domain-authoring.md     # Guides LLM through domain planning conversation → load_domain
├── claude-skills/              # Claude-side skills, symlinked into ~/.claude/skills/
│   └── plansync-domain-authoring/SKILL.md   # Thin wrapper over skills/domain-authoring.md
├── tests/                      # 30 test files, 344 tests
└── docs/
    ├── claude-setup.md         # Claude desktop MCP registration + verification
    └── archive/                # Frozen: v1 spec, shelved v2 PRD, v1 build plan
```

**Sibling repo**: `../reach/` contains Hermes infrastructure (docker-compose.yml, .env). The LIVE Reach data dir is at `$REACH_DATA_PATH` (/Users/michaelkerr/reach-data, mounted at /opt/data) -- `../reach/data/` is only the nightly backup target (mounted at /opt/data-backup); editing config there does nothing. The running containers include `reach-gateway` (main Hermes agent), `reach-plansync` (this project's MCP server + sync pipeline), and `reach-dashboard`; "reach" alone is the compose project name, not a container.

**Deployment**: The `reach-plansync` container is built from this repo's Dockerfile. Code is COPY'd into the image at build time (not volume-mounted -- see D14). Code changes require a rebuild: `cd ../reach && docker compose build plansync && docker compose up -d plansync`. The data volume (`/opt/data/plansync/`) is mounted for DB and domain data. The MCP server runs on port 8082 (SSE transport); Claude Desktop connects via `"url": "http://localhost:8082/sse"` in claude_desktop_config.json. Hermes connects via the Docker network (`http://plansync:8082`). Skills are loaded into Hermes via `external_dirs` (still live-editable via the reach-gateway volume mount of the repo's skills/ directory).

## Module guide
- **State machines**: plansync/engine.py — ACTIVITY_TRANSITIONS, STEP_TRANSITIONS, transition(), react(). All status changes go through here.
- **Plan authoring**: plansync/authoring.py — validate_domain_definition(), validate_activities(), insert_activity(), sync_domain(), resolve_refs(). Returns plain data; server.py wraps in ok()/err().
- **Activity lifecycle**: mcp-server/server.py — _complete_activity(), _defer_activity(), _delete_activity(), _undo(). Each calls transition()+react(), shares a batch_id.
- **Weather evaluation**: sync/sync_pipeline.py — pull_weather(), evaluate_conditions(), _eval_temperature(), _eval_weather_event(). Temperature sustained-days logic in _eval_temperature().
- **Trigger logic**: sync/sync_pipeline.py — evaluate_triggers(), _check_trigger(). Recursive for compound triggers. Calendar triggers fire at prep-window start (target - max_prep_lead_days).
- **View layer**: schema.sql — open_steps, actionable_items, open_activities views. engine.py — get_actionable_items(), get_open_activities(). Used by nudge, briefing, and get_upcoming.
- **Morning briefing**: sync/morning_briefing.py — build_briefing(). Six sections: fires, today, overdue (bundled by activity, capped at MAX_OVERDUE), this week (capped per domain), conditions, weather. Deterministic, zero LLM tokens.
- **Dossier export**: sync/export_dossier.py — render_domain(), render_rotation(). Reads rotation.json for garden-year position.
- **Cron wrappers**: scripts/ — thin delegators copied into /opt/data/scripts/ by register.sh. The actual logic is in sync/ (baked into the container image).

## Conventions
- Database IDs are 12-char hex strings from `uuid4().hex[:12]`
- All DB connections go through `engine.get_db()` or `engine.connect()` (context manager). `busy_timeout=5000`, `foreign_keys=ON`. Journal mode is a persistent DB property set at init/migration: WAL at the APFS location. Never create or move the DB onto the exFAT/VirtioFS mount (WAL breaks there, see DECISIONS.md D5)
- JSON fields in SQLite are stored as TEXT, deserialized on read via `row_to_dict()`
- MCP tool responses use `ok(data)` → `CallToolResult` or `err(message)` → `CallToolResult(isError=True)`. Error responses use the `isError` flag so MCP clients can distinguish errors from data
- Trigger definitions are JSON objects with a `type` field: `calendar`, `condition`, `dependency`, `compound`
- The cron pipeline is deterministic (zero LLM tokens). LLM reasoning happens only in interactive sessions and the morning briefing
- Step dates cascade automatically from activity trigger dates (prep = trigger - lead_days, follow_up = trigger + lead_days)
- Activities carry an optional free-form `group_name` for within-domain bundling (crop, bed, species). Display/organization only -- trigger logic comes from dependency chains, never groups
- A domain = one location/weather context. Activity vs step: needs its own trigger (date, weather, dependency) → activity; fixed-offset chore around a triggered event → step
- weather_log holds ONE row per location per local day, enforced by `UNIQUE(location, weather_date)`. The upsert is `INSERT ... ON CONFLICT DO UPDATE`. Daily high/low are derived from the 3-hourly forecast via derive_daily_range(), not the snapshot
- Conditions rows are DERIVED from trigger_def condition leaves at load/update time (engine.derive_conditions); definitions with an explicit `conditions` array are rejected. The conditions table is an evaluation cache (is_met/current_value), never authored directly
- One authoring path: load_domain (new domain) / add_activities (grow a domain). One modification path: update_activity / update_step / complete_activity / defer_activity / delete_activity (soft skip by default, permanent=true erases)
- Deferral is a date move, not a status: defer_activity requires new_date, rewrites trigger_def via engine.defer_trigger_def, returns the activity to 'watching' so the cron re-fires it. There is no 'deferred' status
- No recurrence, no step conditions, no soil_temp -- validation rejects them with actionable errors. Valid condition metrics: daily_high, daily_low, temp_high, temp_low
- Shared logic lives in `plansync/engine.py`; server.py, sync_pipeline.py, and evening_nudge.py import it and must not define local copies (enforced by tests/test_engine_extraction.py). DB path and client identity resolve from env (`PLANSYNC_DB`, `PLANSYNC_CLIENT`) at call time
- activity_log source attribution: `cron` (sync pipeline), `hermes`/`claude` (via PLANSYNC_CLIENT env), `human` (reserved)
- activity_log.batch_id groups all log entries produced by one operation into one reversible unit for undo. log_change takes optional batch_id; standalone entries stay NULL
- Status changes route through engine.transition() -- validates against transition tables, raises ValueError on invalid moves, returns side-effect events for engine.react(). No raw `UPDATE ... SET status=` anywhere
- undo reverts one batch: statuses via transition(revert), fields from logged old_values (allowlisted per entity). Undoing an undo is refused; created/observation entries are skipped

## Do not
- Do not use class components or ORM -- raw SQL via sqlite3, schemas in schema.sql
- Do not evaluate weather conditions during planning conversations -- the cron job handles that
- Do not delete and recreate activities to modify them -- use update_activity
- Do not add external service dependencies to the automated cron pipeline without asking the user first
- Do not forget to rebuild after code changes: `cd ../reach && docker compose build plansync && docker compose up -d plansync` (code is COPY'd into the image, not volume-mounted -- see D14)
- Do not commit domain data or runtime output to this repo. The repo is code; data lives in reach-data

## Known issues
- **README.md architecture diagram says daily_sync.py**: Renamed to sync_pipeline.py in Step 49. The README diagram hasn't been updated to match.

## Decisions
See DECISIONS.md for the full log with context, alternatives, and consequences. Key decisions: Hermes Agent as runtime (D1), SQLite/WAL (D2), deterministic cron (D3), Telegram-only surface (D4), DB on APFS (D5), AI-agnostic peer access (D6), derived conditions (D7), transition-table state machines (D8), per-domain directories (D9), data outside repo (D10), deferral as date move (D11), MCP isError flag (D12), authoring extraction (D13), standalone container with copied code (D14).


## Development Workflow

This project uses the **product-delivery** lifecycle. All development
work flows through the workflow state machine.

Before starting any work:

1. Call `workflow_status` to check the current state.
2. If no workflow exists, call `workflow_init` to start one.
3. Load the `product_delivery` prompt for full skill instructions.

Rules:

- Follow the workflow transitions. Do not skip states or bypass guards.
- Use `workflow_next` to see what transitions are allowed.
- Transition work items through the submachine:
  ready → implementing → verifying → reviewing → accepted.
- Run tests before and after each work item.
- Record evidence for every transition.
- Update AGENTS.md when new patterns emerge during delivery.
