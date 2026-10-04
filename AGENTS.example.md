<!-- Claude Code: CLAUDE.md in this repo points here. Copy to AGENTS.md for a local always-applied playbook (AGENTS.md is gitignored). -->

# Plan-State

Instructions for agents **working on this repository**. Humans installing or using the product start at [README.md](README.md). Using dispatch from chat (done G1, new path, briefing) is the skills under `skills/`, not this file.

Copy this file to `AGENTS.md` to add local workflow (product-delivery, your deploy). Do not put one machine's compose names in this example.

## What this repo is

Two packages (design intent: [INTENTS.md](INTENTS.md)):

- **dispatch** — the only running service: SQLite store, trigger evaluation, briefing/nudge, completion-code resolver, path instantiation and template checking, MCP server + HTTP API + CLI.
- **planstate** — plan quality library/CLI (no server): domain context schema, reconcile, knowledge-base adapters.

**Repo = code, data volume = state.** Code, schemas, skills, and the three built-in example paths (`dispatch/builtin_paths/`) live here. The dispatch DB and user-authored custom paths live next to the DB (`/data` in Docker, `~/.plansync` locally). Never commit domain data, custom paths, or runtime output.

## Work protocol

This project is still in active delivery. The backlog is [ROADMAP.md](ROADMAP.md) — pick a NOW item; they are not sequenced.

Before starting a NOW item:

1. Run the full test suite. Fix anything broken before adding new work.
2. Read the item's Touches field and those parts of the codebase.
3. Check [DECISIONS.md](DECISIONS.md) for prior decisions that affect this work.

While working:

1. Write or update tests for any behavior you change or add.
2. Follow the conventions below. If a situation is not covered, match the nearest existing pattern. If it is genuinely new, document the convention you choose.
3. If work reveals a new risk, update the item's Risk field.
4. If work uncovers tech debt or a bug unrelated to the current item, add it to ROADMAP.md in the appropriate bucket. Do not fix it now unless it blocks the current work.

When work is done:

1. Update ROADMAP.md: remove the item from NOW, update "What's built" if capabilities changed.
2. Promote an item from Next to NOW if the NOW bucket is thin.
3. Update this file if new conventions or patterns emerged (and `AGENTS.md` if you keep a local copy).
4. Update ARCHITECTURE.md if the system's structure changed.
5. Log significant decisions in DECISIONS.md.

At the start of a session, read this file, ROADMAP.md, and ARCHITECTURE.md. Do not treat Telegram, Hermes, or one operator's compose names as required.

## Tech stack

- **Language**: Python 3 (no type hints in existing code)
- **Database**: SQLite 3, WAL, at `DISPATCH_DB` (Docker: `/data/dispatch.db`; default `~/.plansync/dispatch.db`)
- **MCP**: `mcp>=1.0.0,<2` — SSE over HTTP or stdio
- **HTTP**: Starlette + uvicorn for MCP SSE and the `/api/*` endpoints
- **Templates**: YAML (`pyyaml`)
- **Weather**: OpenWeatherMap current + forecast (`requests`)
- **Runtime**: `docker compose up` from this repo, or `pip install -e .` and `dispatch serve --stdio`. Hermes/Telegram is optional (`hermes/`).
- **Messaging**: the MCP client; Telegram only when Hermes is installed

## Architecture overview

One service (dispatch) owns the DB. Three callers: MCP tools (interactive), the HTTP API (`/api/eval`, `/api/briefing`, `/api/nudge`), and the CLI. Everything reads live DB state at call time — no dossiers, no daily JSON. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Project structure

```
plan-state/
├── README.md                # First-time install, then connect an agent
├── AGENTS.example.md        # Public playbook; copy to AGENTS.md locally
├── INTENTS.md / ROADMAP.md / ARCHITECTURE.md / DECISIONS.md
├── Dockerfile, docker-compose.yml, .env.sample
├── plugin.json, mcp.json    # Agent Plugins v1 (Hermes plugin install)
├── pyproject.toml           # `dispatch` and `plan-state` CLIs
├── dispatch/                # store, eval, paths, instantiate, resolve, briefing, server, cli
│   └── builtin_paths/       # garden-fall, lawn-cool-season, hunting-bow
├── planstate/               # context, reconcile, adapters
├── schemas/                 # item, path, event, domain_context
├── skills/                  # dispatch, plan-state, path-authoring, briefing
├── hermes/                  # optional Telegram install
├── docs/claude-setup.md, docs/migrating-from-plansync.md
└── tests/
```

## Module guide

- **Status changes**: dispatch/store.py — `TRANSITIONS`, `transition()`. Statuses: `watching` → `due` → `done`/`skipped`. Completing an item fires its `after` dependents.
- **Triggers**: dispatch/eval.py — `_check_trigger()` (recursive for compound). Calendar fires at `date - prep_days` (negative prep_days = after the date). Condition fires when every cached rule `is_met` and `earliest_date` has passed.
- **Path templates**: dispatch/paths.py — `validate_path()`, `validate_params()`, `apply_defaults()`, `expand_items()`, `check_path()`, `save_path()`.
- **Instantiation**: dispatch/instantiate.py — refuses invalid templates, applies defaults, inserts items, resolves `after` refs to IDs in insertion order.
- **Completion codes**: dispatch/resolve.py — stable per-domain codes (`G1`), resolver for code/name/ID.
- **Briefing / nudge**: dispatch/briefing.py, dispatch/nudge.py — deterministic, zero LLM tokens.
- **MCP tools** (dispatch/server.py): `status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`, `undo`.

## Conventions

- IDs are 12-char hex from `uuid4().hex[:12]`
- All DB access goes through `dispatch.store.connect()`; `busy_timeout=5000`, `foreign_keys=ON`
- DB path, paths dirs, and client identity resolve from env at call time: `DISPATCH_DB`, `DISPATCH_PATHS_DIR` (built-ins), `DISPATCH_USER_PATHS_DIR` (custom, default `<db dir>/paths`), `DISPATCH_CLIENT`
- JSON fields are TEXT in SQLite, decoded by `row_to_dict()`
- MCP responses use `ok(data)` / `err(message)` (`isError=True`). Validation results the caller must iterate on (draft_path errors) are data, returned with `ok()`
- Status changes go through `transition()`; no raw `UPDATE ... SET status=` outside store.py and undo
- Every write logs to `event_log` with a `batch_id` so `undo` can revert it
- Items are created only by instantiating a path. New kinds of plans mean a new path template, checked with `draft_path` / `dispatch check-path`
- Templates are validated before save and before instantiate. Built-in paths cannot be overwritten; custom paths live in the data volume, never the repo
- Trigger types: `calendar`, `condition`, `after`, `compound`. Condition metrics: `daily_high`, `daily_low`, `temp_high`, `temp_low`. No recurrence, no steps, no soil temperature
- `after` triggers reference refs defined earlier in the template; `event: fired` is rejected until the engine evaluates it
- No domain-specific logic in shared code (`if domain == "garden"` never)
- The hourly job is deterministic. LLM reasoning happens only in interactive sessions

## Do not

- Do not use an ORM — raw SQL via sqlite3; the schema lives in `dispatch/store.py`
- Do not evaluate weather during planning conversations — the hourly job does that
- Do not insert items directly or hand-write templates into the repo — go through `instantiate` and `draft_path`
- Do not add external service dependencies to the hourly job without asking first
- Do not forget to rebuild the dispatch image after code changes (skills are live; code is not)
- Do not commit domain data, custom paths, runtime output, `.env`, `.claude/`, `.cursor/`, or `AGENTS.md`

## Decisions

See [DECISIONS.md](DECISIONS.md). D1–D14 are the legacy plansync system; D15 onward cover dispatch.
