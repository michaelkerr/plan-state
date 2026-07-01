# Build Plan

## Product summary
Plan-state is a condition-aware activity orchestrator for personal life domains. It stores structured plans in SQLite, evaluates triggers daily against weather and calendar conditions, cascades dates through prep/follow-up chains, and syncs actionable tasks to Todoist. The v1 infrastructure is fully built but has never processed real data. The immediate goal is to define a domain authoring pipeline (schema + bulk-load tool + skill) and populate the first domains so the system can run end-to-end.

## Steps

### Step 1: SQLite database and schema
- **Status**: complete
- **What it does**: 7-table schema (domains, activities, steps, conditions, weather_log, todoist_sync, activity_log) with indexes, constraints, WAL mode, foreign keys
- **What good looks like**: `init-db.py` creates the database; schema.sql applied cleanly
- **Test**: none
- **Builds on**: nothing
- **Notes**: Working. Database exists but is empty.

### Step 2: MCP server with 10 tools
- **Status**: complete
- **What it does**: stdio JSON-RPC MCP server exposing get_domains, get_domain_plan, create_domain, create_activity, update_activity, complete_activity, defer_activity, add_observation, get_upcoming, get_weather_current
- **What good looks like**: Hermes can call all tools, create and query domain data
- **Test**: none
- **Builds on**: Step 1
- **Notes**: Working. Auto-creates DB if missing. Bug: `_create_domain` logs item_type as "activity" instead of "domain".

### Step 3: Daily sync pipeline
- **Status**: complete
- **What it does**: 7-step deterministic cron job: weather pull, condition evaluation, trigger evaluation, date re-estimation, overdue check, Todoist sync, summary output
- **What good looks like**: Runs daily at 6 AM, produces JSON summary, syncs tasks to Todoist
- **Test**: none
- **Builds on**: Steps 1-2
- **Notes**: Working. Soil temp always NULL (OpenWeatherMap limitation). Runs but produces empty output since DB has no data.

### Step 4: Morning briefing pipeline
- **Status**: complete
- **What it does**: briefing-context.py reads sync output + DB state, briefing skill instructs LLM to generate human-readable briefing
- **What good looks like**: Concise actionable briefing delivered to Telegram at 6:15 AM
- **Test**: none
- **Builds on**: Step 3
- **Notes**: Working but empty output since no data exists.

### Step 5: Registration script
- **Status**: complete
- **What it does**: register.sh copies skills/scripts to Hermes data dir, initializes DB, installs pip deps, registers MCP server and cron jobs
- **What good looks like**: Single command connects plan-state to a running Hermes instance
- **Test**: manual
- **Builds on**: Steps 1-4
- **Notes**: Working. Needs to be run on Mac Mini with new two-repo layout.

### Step 6: Domain definition schema
- **Status**: complete
- **What it does**: A JSON schema defining a complete domain definition -- one domain with all its activities, steps, conditions, and triggers in a single document. This is the contract between any LLM (Hermes, Claude, etc.) and the system.
- **What good looks like**: Schema validates realistic domain definitions (lawn care, garden, hunting). An LLM can produce a conforming document from a planning conversation. Schema catches common errors (missing required fields, invalid trigger types, bad lead_days).
- **Test**: Write 2-3 example domain definitions (lawn care, garden) and validate them against the schema. Invalid examples should fail validation with clear error messages.
- **Builds on**: Step 1
- **Notes**: See PRD FR-16.1-16.3 for requirements. Keep the format close to what create_activity already accepts to minimize translation.

### Step 7: Bulk load MCP tool (load_domain)
- **Status**: complete
- **What it does**: A new MCP tool that accepts a complete domain definition (conforming to the schema from Step 6), validates it, and atomically creates the domain + all activities + all steps + all conditions in one transaction. Returns the created domain with all IDs assigned.
- **What good looks like**: `load_domain(definition)` creates everything or rolls back on error. Validation errors return structured feedback an LLM can act on (field path, error type, message). Duplicate domain names are rejected.
- **Test**: Load a valid lawn care definition and verify all rows created. Load an invalid definition and verify rollback (zero rows created) with actionable error.
- **Builds on**: Steps 2, 6
- **Notes**: Add to mcp-server/server.py alongside existing tools.

### Step 8: Domain authoring skill
- **Status**: complete
- **What it does**: A skill document (markdown) that teaches an LLM how to run a domain planning conversation and produce a valid domain definition. Covers: how to probe for trigger conditions and lead times, how to structure prep chains, how to format the output, and examples of complete definitions.
- **What good looks like**: A user says "help me plan my fall garden" and the LLM produces a valid domain definition that can be passed directly to load_domain. The skill works with both Hermes (local LLM) and Claude.
- **Test**: manual -- run the skill with a test domain conversation and verify the output validates against the schema
- **Builds on**: Steps 6, 7
- **Notes**: Should be portable across models. For Hermes/smaller models: more structured input, more examples, tighter constraints. See PRD FR-17.1.

### Step 9: Deploy and load first domain
- **Status**: not started
- **What it does**: Deploy the two-repo layout on Mac Mini, run register.sh, then use the authoring skill to create the first real domain (user's choice of lawn care, garden, or hunting).
- **What good looks like**: Domain exists in DB, activities are in "watching" status, next morning's cron run pulls weather and evaluates conditions, Todoist shows tasks for any triggered activities.
- **Test**: manual -- verify cron output JSON has real data, Todoist shows domain project with tasks
- **Builds on**: Steps 5-8
- **Notes**: This is the first end-to-end validation with real data.

### Step 10: Load additional domains
- **Status**: not started
- **What it does**: Use the authoring skill to create 1-2 more domains, validating the workflow is repeatable and cross-domain features work (get_upcoming shows activities from multiple domains, Todoist has multiple projects).
- **What good looks like**: Multiple domains in the system, morning briefing covers all of them, cross-domain upcoming view works.
- **Test**: manual
- **Builds on**: Step 9
- **Notes**: Good time to fix the soil_temp gap -- either find an alternative data source or remove soil_temp triggers from domain definitions.

### Step 11: Fix known bugs
- **Status**: complete
- **What it does**: Fix the `_create_domain` item_type bug (logs "activity" instead of "domain"), consolidate the duplicate DB creation paths (ensure_db in server.py vs init-db.py).
- **What good looks like**: Activity log correctly attributes domain creation. Single canonical DB initialization path.
- **Test**: Create a domain via MCP, verify activity_log row has item_type="domain". Verify only one path creates the DB.
- **Builds on**: Step 2
- **Notes**: Fixed. Removed `ensure_db()` from server.py (DB must be created by `init-db.py` or `register.sh`). Fixed `_create_domain` log_change to use item_type="domain".
