# Decisions

## How to use this file

Each entry captures a decision that affects how the codebase should evolve. Read relevant entries before starting work that touches their area. Add new entries when you make a decision that future work needs to respect.

---

### D1: Hermes Agent, not raw Claude sessions
- **Date**: 2026-06-30
- **Area**: infrastructure, runtime
- **Decision**: Deploy as a capability inside a Hermes Agent instance, not as standalone Claude sessions.
- **Context**: The system needs persistent cross-session memory, a skill system, Telegram integration, and cron scheduling. Building these from scratch would be months of infrastructure work.
- **Alternatives considered**: Raw Claude sessions (no persistence, no cron); a custom bot framework (too much infra to maintain); Home Assistant (wrong abstraction — this is plan management, not device automation).
- **Consequences**: The system depends on Hermes Agent conventions (external_dirs for skills, /opt/data/scripts/ for cron, config.yaml for MCP). Upgrades to Hermes may require adaptation. The split-repo pattern (plan-state + reach) keeps this manageable.

---

### D2: SQLite, not Postgres
- **Date**: 2026-06-30
- **Area**: database
- **Decision**: Use SQLite with WAL journal mode for persistence.
- **Context**: Single-user system on a home server. No concurrent writers beyond the cron pipeline and occasional MCP calls.
- **Alternatives considered**: Postgres (adds a database server process for no benefit at this scale).
- **Consequences**: The DB file must live on an APFS-backed path (see D5). busy_timeout=5000 handles the rare cron/MCP overlap. No connection pooling needed.

---

### D3: Deterministic cron, not LLM-in-the-loop
- **Date**: 2026-06-30
- **Area**: sync pipeline, architecture
- **Decision**: Weather evaluation, trigger logic, date cascading, and overdue checking are all rule-based Python. Zero LLM tokens in the cron pipeline.
- **Context**: These operations are deterministic — the same inputs always produce the same outputs. Using an LLM would add cost, latency, and a failure mode for no benefit.
- **Alternatives considered**: LLM-mediated evaluation (could handle fuzzier conditions but adds fragility and cost for a pipeline that runs hourly).
- **Consequences**: The cron pipeline has no API cost and no external dependency beyond OpenWeatherMap. Adding new condition types requires code changes, not prompt changes.

---

### D4: Telegram as sole task surface
- **Date**: 2026-07-19
- **Area**: integrations, user experience
- **Decision**: Remove Todoist integration. Telegram (via Hermes) is the only surface for viewing and completing tasks.
- **Context**: Todoist was ~300 lines of sync code and the system's most fragile external dependency. Its API sunset broke the pipeline once. The completion-polling model (once daily at 6 AM) meant completions were laggy. Conversational completion through Telegram is immediate, captures notes, and has zero external dependency.
- **Alternatives considered**: Keeping Todoist as a read-only view (still fragile, still a maintenance burden); other task apps (same integration problems).
- **Consequences**: Completions require talking to Hermes or Claude — no checkbox UI. The evening nudge replaces Todoist's due-time reminders.

---

### D5: DB on APFS, never on exFAT/VirtioFS
- **Date**: 2026-07-11
- **Area**: database, deployment
- **Decision**: The SQLite database must live at /opt/data/plansync/plansync.db (APFS-backed Hermes data directory), never on the repo's volume mount.
- **Context**: SQLite WAL mode fails silently on exFAT and VirtioFS mounts (the Docker volume pass-through for the repo). This caused data corruption during a 2 AM debugging session on 2026-07-11. The DB was migrated to the APFS-backed path and the failure mode was documented.
- **Alternatives considered**: Switching to DELETE journal mode (works on exFAT but slower and less concurrent); keeping the DB in the repo directory (too risky).
- **Consequences**: The DB path is hardcoded to /opt/data/plansync/plansync.db, overridable by PLANSYNC_DB env var (for tests). init-db.py and all migrations target this path.

---

### D6: AI-agnostic peer access
- **Date**: 2026-07-20
- **Area**: MCP server, multi-agent
- **Decision**: Claude registers the same MCP server as Hermes via docker exec. Both are equal peers of the same engine, distinguished only by activity_log.source (hermes/claude).
- **Context**: The user works with both Claude (desktop/mobile) and Hermes (Telegram). Both should be able to read and write plan state without coordination overhead.
- **Alternatives considered**: Separate databases per agent (drift); read-only access for Claude (too limiting); a REST API layer (unnecessary complexity for two clients).
- **Consequences**: The MCP server process is stateless (one per session). PLANSYNC_CLIENT env var controls source attribution. The domain-authoring skill is shared (Claude's skill is a thin wrapper pointing to the canonical file).

---

### D7: Conditions derived from trigger_def
- **Date**: 2026-07-21
- **Area**: data model, MCP server
- **Decision**: The conditions table is an evaluation cache derived from condition-type leaves in trigger_def. Explicit conditions arrays in API input are rejected.
- **Context**: v1 had separate conditions arrays that could diverge from trigger_def. The derive_conditions() function in engine.py walks the trigger_def tree and generates conditions rows automatically. One source of truth.
- **Alternatives considered**: Keeping separate conditions (more flexible but error-prone); removing the conditions table entirely (lose the evaluation cache for the cron).
- **Consequences**: Any change to trigger_def must re-derive conditions (delete + re-insert). Validation rejects the old conditions array format with an actionable error message.

---

### D8: State changes through transition tables
- **Date**: 2026-07-24
- **Area**: engine, state management
- **Decision**: All status changes route through transition() + react() in engine.py. No raw UPDATE ... SET status= anywhere.
- **Context**: v1 had raw status updates scattered across server.py, sync_pipeline.py, and evening_nudge.py. This made undo impossible (no way to know what side effects to reverse) and made invalid transitions easy to introduce silently.
- **Alternatives considered**: A simpler "validate before update" pattern (doesn't handle cascade side effects); keeping raw updates with better logging (doesn't prevent invalid transitions).
- **Consequences**: Adding a new status or transition requires updating the tables in engine.py. The react() function handles all cascade logic (step completion, follow-up promotion, dependency firing) in one place.

---

### D9: Per-domain directories
- **Date**: 2026-07-22
- **Area**: data layout, Claude sessions
- **Decision**: Each domain owns a domains/{slug}/ directory containing its definition JSON, reference docs, rotation config, and daily dossier.
- **Context**: Claude sessions should be able to connect to one domain's directory without loading every domain's context. Cross-domain context bleed was making sessions less focused.
- **Alternatives considered**: One flat directory (simpler but blurs domain boundaries); subdirectories inside the repo (mixes runtime data with source code — see D10).
- **Consequences**: Dossier exporter writes to domains/{slug}/dossier.md. Rotation configs and reference docs live alongside.

---

### D10: Domain data outside the repo
- **Date**: 2026-08-17
- **Area**: repo structure, deployment
- **Decision**: All domain data and runtime output moved from the repo working tree to /opt/data/plansync/ (host: $REACH_DATA_PATH/plansync/).
- **Context**: The repo was doubling as the runtime data directory — cron exporters wrote generated files back into it, and hand-authored domain configs were versioned alongside system code. This blurred the line between source and state.
- **Alternatives considered**: .gitignore-based separation (fragile, still in the working tree); a separate data repo (unnecessary complexity).
- **Consequences**: The repo is pure code. PLANSYNC_DOMAINS_DIR and PLANSYNC_OUTPUT_DIR env vars point to the data directory (defaulting to /opt/data/plansync/). The data directory is covered by the nightly reach-data backup.

---

### D11: Deferral is a date move, not a status
- **Date**: 2026-07-12
- **Area**: data model, MCP server
- **Decision**: defer_activity requires a new_date, rewrites trigger_def (via engine.defer_trigger_def), and returns the activity to 'watching' so the cron re-fires it. There is no 'deferred' status.
- **Context**: A deferred activity is still the same activity with the same trigger logic — it just can't fire before the new date. Adding a 'deferred' status would complicate the state machine and require special handling in the cron.
- **Alternatives considered**: A 'deferred' status with a resume_date field (more states to manage, cron needs to scan another status).
- **Consequences**: defer_trigger_def handles all trigger types: calendar dates move directly, compound calendar legs move, condition/dependency triggers get wrapped in a compound AND with an earliest-date gate.

---

### D12: MCP errors via CallToolResult isError flag
- **Date**: 2026-08-21
- **Area**: MCP server
- **Decision**: MCP tool errors use `CallToolResult(isError=True)` via an `err()` helper, separating error responses from data at the protocol level. `ok()` wraps success data into a `CallToolResult`.
- **Context**: Previously, errors were returned as normal `ok({"error": ...})` responses, indistinguishable from data at the MCP protocol level. A future CLI or dashboard client would have to parse the JSON body to detect errors.
- **Alternatives considered**: HTTP-style status codes in the response body (more complex, not MCP-native).
- **Consequences**: MCP clients can detect errors from the `isError` flag without parsing the body. Authoring functions in plansync/authoring.py return plain data and raise ValueError; server.py wraps with ok()/err().

---

### D13: Extract authoring logic from server.py
- **Date**: 2026-08-22
- **Area**: architecture, plansync/authoring.py
- **Decision**: Validation, insertion, sync, and ref resolution logic moved from mcp-server/server.py to plansync/authoring.py. Authoring functions return plain data (dicts/lists) and raise ValueError; server.py wraps with ok()/err().
- **Context**: server.py was 800+ lines mixing MCP tool dispatch with domain authoring logic. Separating them makes authoring testable without MCP and reusable from a future CLI.
- **Alternatives considered**: Keeping everything in server.py (simpler, but limits reuse); moving to engine.py (engine handles state machines and DB access, not business-rule validation).
- **Consequences**: New module plansync/authoring.py. Server.py imports from it. Tests that validated server.py private functions now import from plansync.authoring.

---

### D14: Standalone plansync container, code copied not mounted
- **Date**: 2026-08-27
- **Area**: deployment, containers
- **Decision**: The plansync MCP server runs in its own container (`reach-plansync`) built from the plan-state Dockerfile. Code is COPY'd into the image at build time, not volume-mounted.
- **Context**: The previous setup volume-mounted the entire repo into reach-gateway, which was brittle — filesystem differences (exFAT/VirtioFS) caused WAL failures (D5), and the tight coupling between the repo working tree and the running container made it easy to break production with an uncommitted edit. The standalone container with copied code is simpler and more predictable: the running code matches the built image, period.
- **Alternatives considered**: Keeping the volume mount (faster iteration but fragile); a dev-mode compose override with a volume mount (complexity for a single-developer project).
- **Consequences**: Code changes require a container rebuild (`docker compose build plansync && docker compose up -d plansync` from the reach directory). The data volume (`/opt/data`) is still mounted. CLAUDE.md's volume-mount documentation needs updating. Claude Desktop connects via SSE URL (`http://localhost:8082/sse`), not `docker exec`.

---

### D15: Custom path templates are data, validated before save and instantiate
- **Date**: 2026-09-25
- **Area**: dispatch, path templates
- **Decision**: User-authored path templates are saved through `draft_path(save=true)` / `dispatch check-path --save` into `DISPATCH_USER_PATHS_DIR` (default `<db dir>/paths`, i.e. the container's `/data` volume), not the repo. Built-in example paths stay in `paths/` and cannot be overwritten. `validate_path()` runs before every save and every `instantiate`; structural errors block, warnings (hardcoded dates, unused params, per-entity dependencies) only inform. Validation lives in `dispatch/paths.py` next to the expansion code so the preview and real instantiation expand templates identically.
- **Context**: Items can only be created from paths, so a plan the three built-ins don't cover needed a hand-written YAML file baked into the image. The engine silently ignores unknown trigger types and misspelled fields (the item just never fires), so an unchecked template fails invisibly weeks later.
- **Alternatives considered**: Saving custom templates into the repo (mixes user data with code, needs a rebuild per template); letting agents write files directly (no validation, path traversal risk); a separate `save_path` tool (grows the tool surface; save is one flag on the same check the agent already runs); putting validation in `planstate` (instantiate lives in dispatch and must enforce it).
- **Consequences**: One new MCP tool (`draft_path`), 8 total. Custom templates share the dispatch DB's backup exposure (see ROADMAP "Back up the dispatch DB"). The Claude Desktop MCP entry now runs `dispatch serve --stdio` in `reach-plansync-new` via `docker exec`.
