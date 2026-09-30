<!-- If using multiple AI coding tools, symlink this to AGENTS.md: ln -s CLAUDE.md AGENTS.md -->

# Plan-State

## What this is
A condition-aware task system for personal life domains (lawn, garden, hunting, home). Reusable YAML **path templates** are instantiated into **items** with triggers (date, weather, another item finishing, or a mix). An hourly deterministic job (zero LLM tokens) pulls weather and fires triggers; a morning briefing (6:15) and evening nudge (5 PM, silent when clear) go to Telegram with stable completion codes like `G1` or `L2`. The user replies "done G1" to Reach (Hermes, on Telegram) or tells Claude, and the agent calls the `done` tool. Hermes and Claude are peer clients of the same MCP server, with writes attributed by `DISPATCH_CLIENT`.

The repo holds two packages (see INTENTS.md for the design intent):
- **dispatch** -- the execution engine and the only running service: SQLite store, trigger evaluation, briefing/nudge, completion-code resolver, path instantiation and template checking, MCP server + HTTP API + CLI.
- **planstate** -- plan quality library/CLI (no server): generic domain context schema, reconcile (dispatch items vs domain context), knowledge-base adapters (YAML, Obsidian).

**Repo = code, data volume = state.** The repo holds code, schemas, skills, and the three built-in example paths. Runtime state -- the dispatch DB and user-authored custom paths -- lives in the container's `/data` volume. Never commit domain data, custom paths, or runtime output.

**Legacy system still in the repo.** `plansync/`, `mcp-server/`, `sync/`, `schema.sql`, and the `reach-plansync` container are the pre-dispatch system. Hermes has it disabled (`enabled: false` in Reach's config.yaml) and Claude Desktop no longer points at it. It stays until MIGRATION.md Phase 4 removes it; do not build new features on it.

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
- **Database**: SQLite 3, WAL, at `DISPATCH_DB` (container: `/data/dispatch.db` on the `plansync-new-data` Docker volume; default `~/.plansync/dispatch.db`)
- **MCP**: `mcp>=1.0.0,<2` -- SSE over HTTP (Hermes) or stdio (Claude Desktop, plugin installs)
- **HTTP**: Starlette + uvicorn for MCP SSE and the `/api/*` endpoints
- **Templates**: YAML (`pyyaml`)
- **Weather**: OpenWeatherMap current + forecast (`requests`)
- **Runtime**: `reach-plansync-new` container built from `Dockerfile.dispatch`, alongside Hermes Agent (Reach) on a Mac Mini
- **Messaging**: Telegram via the Hermes gateway

## Architecture overview
One service (dispatch) owns the DB. Three callers: the MCP tools (interactive, Hermes and Claude), the HTTP API (Hermes cron jobs curl `/api/eval`, `/api/briefing`, `/api/nudge`), and the CLI (inside the container or locally). Everything reads live DB state at call time -- no dossiers, no daily JSON. See ARCHITECTURE.md for the component map and data flow.

## Project structure
```
plan-state/
├── INTENTS.md               # Design intent: two-layer model, vocabulary, non-goals
├── MIGRATION.md             # Old plansync → dispatch parallel-run cutover
├── ROADMAP.md / ARCHITECTURE.md / DECISIONS.md
├── Dockerfile.dispatch      # The running image (reach-plansync-new)
├── docker-compose.plansync.yaml  # Compose override for the parallel-run service
├── plugin.json, mcp.json    # Agent Plugins v1 packaging (Hermes plugin install)
├── pyproject.toml           # Installs `dispatch` and `plan-state` CLIs
├── dispatch/
│   ├── store.py             # Schema, connections, items CRUD, transitions, event log
│   ├── eval.py              # Weather pull, condition cache, trigger firing
│   ├── paths.py             # Path templates: load/list, validate, expand, preview, save
│   ├── instantiate.py       # Validated template → items in the DB
│   ├── resolve.py           # Code/name/ID resolver and stable code assignment
│   ├── briefing.py, nudge.py# Deterministic Telegram text
│   ├── doctor.py            # Health checks (/health)
│   ├── server.py            # MCP tools + HTTP API
│   └── cli.py               # `dispatch ...`
├── planstate/               # context.py, reconcile.py, adapters/, cli.py (`plan-state ...`)
├── schemas/                 # item.yaml, path.yaml, event.yaml, domain_context.yaml
├── paths/                   # Built-in example templates (garden-fall, lawn-cool-season, hunting-bow)
├── skills/                  # Hermes skills, loaded live via external_dirs
│   ├── dispatch/            # Close/skip/defer/list by code
│   ├── plan-state/          # Set up a domain from a path
│   ├── path-authoring/      # Build a new path template with draft_path
│   └── briefing/            # Briefing presentation
├── claude-skills/           # Claude wrappers pointing at skills/ (symlinked into ~/.claude/skills)
├── scripts/dispatch-*.sh    # Cron wrappers: curl the dispatch HTTP API
├── tests/                   # test_dispatch, test_paths, test_path_authoring, test_planstate + legacy tests
└── (legacy) plansync/, mcp-server/, sync/, schema.sql, Dockerfile, register.sh
```

**Sibling repo**: `../reach/` holds the Hermes compose file and `.env`. Live Hermes config is `$REACH_DATA_PATH/config.yaml` (`/Users/michaelkerr/reach-data/config.yaml`); `../reach/data/` is only the backup target. Containers: `reach-gateway` (Hermes), `reach-plansync-new` (dispatch, host port 8083), `reach-plansync` (legacy, host port 8082), `reach-dashboard`.

**Deployment**: Code is COPY'd into the image. After code changes: `docker build -f Dockerfile.dispatch -t plansync-dispatch:latest . && cd ../reach && docker compose up -d plansync-new`. Hermes reaches MCP at `http://plansync-new:8082/sse`. Claude Desktop runs `docker exec -i -e DISPATCH_CLIENT=claude reach-plansync-new dispatch serve --stdio` (restart Claude Desktop after changing its config). Skills are live: Hermes loads `/opt/projects/plan-state/skills` via `external_dirs`.

## Module guide
- **Status changes**: dispatch/store.py -- `TRANSITIONS`, `transition()`. Statuses: `watching` → `due` → `done`/`skipped`. Completing an item fires its `after` dependents.
- **Triggers**: dispatch/eval.py -- `_check_trigger()` (recursive for compound). Calendar fires at `date - prep_days` (negative prep_days = after the date). Condition fires when every cached rule `is_met` and `earliest_date` has passed.
- **Path templates**: dispatch/paths.py -- `validate_path()` (structural errors/warnings), `validate_params()`, `apply_defaults()`, `expand_items()`, `check_path()` (validate + preview with plain-English `when`), `save_path()`.
- **Instantiation**: dispatch/instantiate.py -- refuses invalid templates, applies defaults, inserts items, resolves `after` refs to IDs in insertion order.
- **Completion codes**: dispatch/resolve.py -- stable per-domain codes (`G1`), resolver for code/name/ID.
- **Briefing / nudge**: dispatch/briefing.py, dispatch/nudge.py -- deterministic, zero LLM tokens.
- **MCP tools** (dispatch/server.py): `status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`, `undo`.

## Conventions
- IDs are 12-char hex from `uuid4().hex[:12]`
- All DB access goes through `dispatch.store.connect()`; `busy_timeout=5000`, `foreign_keys=ON`
- DB path, paths dirs, and client identity resolve from env at call time: `DISPATCH_DB`, `DISPATCH_PATHS_DIR` (built-ins), `DISPATCH_USER_PATHS_DIR` (custom, default `<db dir>/paths`), `DISPATCH_CLIENT`
- JSON fields are TEXT in SQLite, decoded by `row_to_dict()`
- MCP responses use `ok(data)` / `err(message)` (`isError=True`). Validation results the caller must iterate on (draft_path errors) are data, returned with `ok()`
- Status changes go through `transition()`; no raw `UPDATE ... SET status=` outside store.py and undo
- Every write logs to `event_log` with a `batch_id` so `undo` can revert it
- Items are created only by instantiating a path. New kinds of plans mean a new path template, authored with the path-authoring skill and checked with `draft_path` / `dispatch check-path`
- Templates are validated before save and before instantiate. Built-in paths cannot be overwritten; custom paths live in the data volume, never the repo
- Trigger types: `calendar`, `condition`, `after`, `compound`. Condition metrics: `daily_high`, `daily_low`, `temp_high`, `temp_low`. No recurrence, no steps, no soil temperature
- `after` triggers reference refs defined earlier in the template; `event: fired` is rejected until the engine evaluates it
- No domain-specific logic in shared code (`if domain == "garden"` never)
- The hourly job is deterministic. LLM reasoning happens only in interactive sessions

## Do not
- Do not use an ORM -- raw SQL via sqlite3; the schema lives in `dispatch/store.py`
- Do not evaluate weather during planning conversations -- the hourly job does that
- Do not insert items directly or hand-write templates into the repo -- go through `instantiate` and `draft_path`
- Do not add external service dependencies to the hourly job without asking the user first
- Do not forget to rebuild the dispatch image after code changes (skills are live; code is not)
- Do not commit domain data, custom paths, or runtime output
- Do not build on the legacy plansync code

## Known issues
- **Dispatch DB is not in the nightly backup**: it lives on the `plansync-new-data` Docker volume, not under `$REACH_DATA_PATH`. See ROADMAP.md.
- **README.md describes the legacy system**: setup, how-it-works, and the diagram predate dispatch.

## Decisions
See DECISIONS.md for the full log. Decisions D1-D14 cover the legacy plansync system; D15 onward cover dispatch.


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
