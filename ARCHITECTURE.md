# Architecture

## System overview

dispatch is a single SQLite-backed service that stores items with triggers, evaluates them hourly against the weather, and produces briefings. A first-time install is `docker compose up` from this repo (see README.md) or `pip install -e .` plus `dispatch serve --stdio`. Three callers share it: MCP tools (SSE or stdio), an HTTP API (`/api/eval`, `/api/briefing`, `/api/nudge`), and a CLI. Items are created only by instantiating path templates; plan-state (`planstate/`) is a library/CLI, not a service. Optional Telegram install: [hermes/README.md](hermes/README.md).

## Component map

### dispatch/store.py — storage and state

- **Purpose**: Schema, connections, item CRUD, status transitions, event log, condition cache derivation.
- **Tables**: `items`, `event_log`, `weather_log` (one row per location per day), `conditions_cache` (derived from condition triggers, never authored).
- **Key patterns**:
  - `connect()` — context manager; busy_timeout and foreign keys on every connection
  - `transition(conn, item_id, event)` — validates against `TRANSITIONS`, updates the row, logs old/new values, fires `after` dependents on completion
  - `_defer_trigger()` — deferral rewrites the trigger date and returns the item to `watching`
  - `derive_conditions()` — rebuilds cache rows from a trigger's condition leaves

### dispatch/eval.py — hourly evaluation (zero LLM tokens)

- **Entry point**: `run_eval(location)`; called by `GET/POST /api/eval` and `dispatch eval`
- **Stages**: `pull_weather()` → `evaluate_conditions()` (consecutive-day counting) → `evaluate_triggers()` (fires due items via `transition`)
- **Trigger rules**: calendar fires at `date - prep_days` (negative = after); condition when all cached rules are met and `earliest_date` has passed; after when the referenced item is done plus `offset_days`; compound combines with and/or

### dispatch/paths.py — path templates

- **Purpose**: Everything about templates that does not touch the DB.
- **Locations**: built-ins ship in the package (`dispatch/builtin_paths/`, overridable with `DISPATCH_PATHS_DIR`); custom templates in `DISPATCH_USER_PATHS_DIR` (default `<db dir>/paths`)
- **Key functions**:
  - `validate_path()` — structural errors (block save/instantiate) and warnings (hardcoded dates, unused params, after-triggers pointed at per-entity items)
  - `validate_params()` / `apply_defaults()` — supplied values against declared params
  - `expand_items()` — substitutes params and per-entity copies; shared by preview and instantiate
  - `check_path()` — validate + preview with a plain-English `when` per item
  - `save_path()` — validates and writes the YAML text (comments preserved); refuses built-in ids

### dispatch/instantiate.py — template → items

- Validates the template and params, applies defaults, expands, inserts items in order, resolves `after` refs to real IDs, derives conditions, logs one batch.

### dispatch/resolve.py, briefing.py, nudge.py — Telegram surfaces

- Stable per-domain completion codes (`G1`, `L2`) and a resolver that accepts a code, name substring, or ID.
- Briefing and nudge are deterministic text built from live DB state; the nudge is empty when nothing is open.

### dispatch/server.py — MCP + HTTP

- **MCP tools**: `status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`, `undo`
- **HTTP API** (`--api`): `/health` (doctor), `/api/eval`, `/api/briefing`, `/api/nudge`, `/api/status`
- **Transports**: `dispatch serve --http --api` (container default), `dispatch serve --stdio` (Claude Desktop via `docker exec`, plugin installs)

### dispatch/cli.py — `dispatch`

- `init`, `serve`, `eval`, `briefing`, `nudge`, `doctor`, `status`, `done`, `defer`, `paths`, `instantiate`, `check-path`

### planstate/ — plan quality library

- `context.py` — generic domain context (entities, params, active paths) in YAML under `PLANSTATE_CONTEXT_DIR`
- `reconcile.py` — flags drift between dispatch items and the domain context
- `adapters/` — YAML (default) and Obsidian frontmatter readers

## Data flow

### Hourly eval (cron, zero tokens)

1. Scheduler (built-in loop, or Hermes cron) hits `GET/POST /api/eval` (Hermes: `curl http://dispatch:8082/api/eval`)
2. `pull_weather` upserts today's weather_log row (high/low from the 3-hourly forecast and current temp)
3. `evaluate_conditions` updates consecutive-day counts and `is_met` for watching items
4. `evaluate_triggers` fires items whose triggers are satisfied → status `due`, `due_date` set

### Briefing and nudge

1. 6:15 cron curls `/api/briefing`; 5 PM cron curls `/api/nudge`
2. Text is delivered verbatim to Telegram with completion codes; an empty nudge sends nothing

### Completion

1. User replies "done G1, skip H3" on Telegram (or tells Claude)
2. The dispatch skill makes one `done`/`skip` call per code; `resolve()` maps code → item
3. `transition(complete)` marks it done and fires `after` dependents; one batch, undoable

### Template authoring

1. User asks for a plan no existing path covers; the path-authoring skill runs the conversation
2. Agent drafts YAML and calls `draft_path(yaml, params)` until `valid` is true; the user reviews the preview
3. `draft_path(yaml, save=true)` writes it to the custom paths dir
4. The plan-state skill (or the user) calls `instantiate(path_id, domain, params)`

### Domain setup from an existing path

1. plan-state skill collects entities and params
2. `draft_path(path_id, params)` previews; user confirms
3. `instantiate` creates the items; they appear in the next briefing

## Data model

- **item**: one actionable unit with a trigger, optional group and checklist, `source_ref` (path ref + entity) and `path_id` (`id@version`) for provenance
- **event_log**: append-only; every change with `batch_id`, source (`DISPATCH_CLIENT`), old/new values
- **conditions_cache**: evaluation cache derived from condition triggers
- **weather_log**: one row per location per local day

## Integration points

- **OpenWeatherMap** — current + 5-day/3-hour forecast, once per eval. Failures return empty data and later stages still run.
- **Hermes Agent** (optional) — MCP over SSE; cron curls the HTTP API; skills from this repo's `skills/`. See [hermes/README.md](hermes/README.md).
- **Claude Desktop / Cursor** — MCP over SSE (`http://127.0.0.1:8082/sse` for Docker Compose) or stdio (`dispatch serve --stdio`)
- **Telegram** — briefing and nudge via Hermes when that install is used

## Deployment topology

`docker compose up` in this repo: container `dispatch`, volume `dispatch-data`, host port 8082, built-in eval every 60 minutes.

Hermes installs put dispatch on the same Docker network (service name `dispatch`) and turn the built-in scheduler off.
