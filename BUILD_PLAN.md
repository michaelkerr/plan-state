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
- **Builds on**: Steps 5-8, 12-14
- **Notes**: This is the first end-to-end validation with real data. Do Steps 12-14 first so the schema is final before real data exists (no migration needed on an empty DB).

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

### Step 12: Activity grouping
- **Status**: complete
- **What it does**: Adds a free-form `group_name` TEXT column to activities for within-domain bundling (crop name, garden bed, food plot, etc.). Carries no trigger logic -- display and organization only. Supported in the domain definition schema, load_domain, create_activity, update_activity, get_domain_plan, and get_upcoming. briefing-context.py groups activities by it. Todoist sync uses it in task naming or as a section so bundles read together.
- **What good looks like**: A garden domain can have "Start Tomato Seeds", "Transplant Tomatoes", and "Tomato Harvest Watch" all under group "Tomatoes"; get_upcoming and the morning briefing present them as one bundle. Activities without a group behave exactly as today.
- **Test**: Load a domain definition with grouped and ungrouped activities; verify group_name persists, get_domain_plan and get_upcoming return it, and briefing context output groups by it.
- **Builds on**: Steps 6, 7
- **Notes**: Rationale: the bundling layer between domain and activity (plant type, species, bed) is not one fixed taxonomy, so it's a free-form field rather than a table. Domain = one location/weather context; dependency chains + group_name handle bundling within it. Built 2026-07-02: column named `group_name` (not `group` -- SQL keyword). Todoist tasks are prefixed "Group: Task" via task_content() in daily_sync.py; steps inherit the group from their parent activity. Local plansync.db (empty, gitignored) was deleted and re-initialized from the updated schema. Mac Mini DB re-init happens at Step 9 deploy. Regression tests in tests/test_group_name.py (10 tests); the Todoist naming test skips locally without `requests` installed.

### Step 13: Amend-domain MCP tool (add_activities)
- **Status**: complete
- **What it does**: A new MCP tool that adds one or more activities (with steps and conditions) to an existing domain, using the same activity-definition format as load_domain. Validates like load_domain, atomic (all-or-nothing), and resolves dependency `activity_ref` names against BOTH the incoming batch and activities already in the domain -- so a new "Transplant Tomatoes" can depend on an existing "Start Tomato Seeds".
- **What good looks like**: `add_activities(domain_id, activities=[...])` creates everything or rolls back with structured errors. Duplicate activity names within the domain are rejected. New activities start in "watching" status and are picked up by the next cron run with no special handling.
- **Test**: Load a domain, then add an activity whose dependency trigger references a pre-existing activity by name; verify resolution to the correct ID. Add an invalid batch; verify rollback (zero new rows) and actionable errors.
- **Builds on**: Steps 7, 12
- **Notes**: load_domain stays create-only. Existing update_activity/complete_activity/defer_activity already cover editing; this fills the "grow an existing domain" gap. Built 2026-07-02: activity insert logic extracted into shared _insert_activity() used by both load_domain and add_activities; validation generalized via _validate_activities(existing_names). sort_order for new activities continues after the domain's current max. Regression tests in tests/test_add_activities.py (14 tests). Building this surfaced the pending_create gap fixed in Step 15.

### Step 14: Domain authoring skill v2 (create + amend)
- **Status**: not started
- **What it does**: Updates skills/domain-authoring.md to manage domains over their lifetime, not just create them. Adds: (1) amend mode -- when the user names an existing domain, fetch it with get_domain_plan, run the same probing for just the new activities, call add_activities; (2) domain-scoping guidance -- a domain is one location/weather context and a coherent plan (Garden, Yard, TN Hunting Prop 1), not a broad life category; (3) the activity-vs-step rule -- if it needs its own trigger (date, weather, or "after X completes") it's an activity, if it's a fixed-offset chore around a triggered event it's a step; (4) group_name guidance with a multi-phase crop example (tomatoes as a 3-activity dependency chain under one group).
- **What good looks like**: "Add tomatoes to my garden" produces grouped, dependency-chained activities added to the existing Garden domain via add_activities. "Help me plan my garden" still produces a fresh load_domain call. The skill picks the right mode without being told.
- **Test**: manual -- run one create conversation and one amend conversation; verify the amend path calls get_domain_plan first and produces a valid add_activities payload referencing an existing activity
- **Builds on**: Steps 8, 12, 13
- **Notes**: Single skill file for both modes so the trigger-format reference isn't duplicated.

### Step 15: Todoist enqueue reconciliation
- **Status**: complete
- **What it does**: Fixes a v1 gap: nothing ever writes `pending_create` rows to todoist_sync, so no task would ever be created in Todoist. Adds a reconciliation pass in daily_sync.py just before the Todoist step: enqueue pending_create for (a) any activity in status preparing/active with no todoist_sync row, and (b) any pending/due step with a due_date whose parent activity is preparing/active and which has no todoist_sync row. Idempotent -- catches status changes from any source (cron trigger fire, Hermes tools, Todoist completion polling).
- **What good looks like**: After a trigger fires, the next sync run creates Todoist tasks for the activity and its steps. Running the sync twice does not enqueue duplicates. Completed/skipped items are never enqueued.
- **Test**: Seed a DB with a preparing activity + steps, run the reconciliation function, verify pending_create rows exist and are correct; run again, verify no duplicates; verify watching/completed activities and completed steps are not enqueued.
- **Builds on**: Step 3
- **Notes**: Found while building Step 13. Reconciliation in the cron (rather than enqueue calls at every status-change site) fits the deterministic-pipeline design and self-heals missed enqueues. Must land before Step 9, whose verification requires tasks appearing in Todoist. Built 2026-07-02: enqueue_todoist_items() runs as its own pipeline step before todoist_sync, so the queue fills even when TODOIST_API_KEY is unset. Also made the `requests` import guarded so sync code is importable in test environments without network deps. Tests in tests/test_todoist_enqueue.py (6 tests).

### Step 16: Derive daily high/low from forecast
- **Status**: complete
- **What it does**: Fixes a trigger-correctness bug: the weather pull stores the current-weather snapshot's temp_max/temp_min, which at a single reading are both ~equal to the instantaneous temp. A 6 AM cron run records the morning temp as the day's "high", so triggers like daily_high <= 85 fire on cool mornings regardless of afternoon heat. Fix: derive daily_high/daily_low from the 3-hourly forecast already fetched each run -- group forecast entries by LOCAL calendar day (city.timezone offset; entries are UTC), take max/min of today's temps, blend with the current reading (max for high, min for low). Falls back to the current reading if no forecast entries remain for today.
- **What good looks like**: weather_log rows show a realistic spread (e.g. high 97 / low 70, not 91/91). A morning run correctly represents the coming afternoon peak, so "is today a <=85 day" triggers fire the morning of a qualifying day.
- **Test**: Pure function derive_daily_range(current_temp, forecast_data, now_utc) tested against a canned forecast payload: blending in both directions, UTC-to-local day boundary (00:00 UTC entry belongs to the previous local day in UTC-5), and the no-entries-left fallback.
- **Builds on**: Step 3
- **Notes**: Zero new API calls or dependencies -- uses the forecast response already stored in forecast_json. Chosen over One Call daily summary (separate subscription) and a second evening cron run (still a snapshot, misses the peak). A 6 AM trigger decision about "today" should use the forecast anyway: the observed high isn't knowable until evening. Built 2026-07-02: verified live in-container -- old snapshot row 90.97/90.97 vs derived 88.1/78.8. Tests in tests/test_weather_range.py (9 tests). Caveat recorded: weather_log assumes one row per location per day (sustained_days reads the last N rows); manual sync runs create duplicates, so clean up extra same-day rows after ad-hoc verification runs.

### Step 17: Early Todoist validation task
- **Status**: awaiting verification (2026-07-03 morning cron)
- **What it does**: Adds a throwaway "Todoist Sync Test" activity (group "System") to the Yard domain with a calendar trigger of 2026-07-03 and one follow-up step, loaded via the add_activities tool (dogfooding Step 13 against the live DB). Tomorrow's 6 AM cron should: fire the trigger (no prep steps -> status active), enqueue both the activity and its step via the Step 15 reconciliation, and create two Todoist tasks in the Yard project with the "System: " group prefix. Completing them in Todoist then exercises the completion-polling path on the following run.
- **What good looks like**: Two tasks in Todoist by ~6:05 AM on 2026-07-03: "System: Todoist Sync Test" and "System: Confirm test tasks appeared, then complete both". Validates trigger fire -> enqueue -> task creation -> (on completion) poll-back, without waiting for the fungicide trigger ~July 5.
- **Test**: manual -- observe Todoist tomorrow morning; after completing the tasks there, confirm the activity shows completed in the DB the following day
- **Builds on**: Steps 9, 13, 15
- **Notes**: Cleanup: after verification, the activity is already completed via the Todoist poll; no deletion needed (completed activities are inert). Validates the full loop early. 2026-07-03: task creation failed with 410 Gone -- Todoist sunset REST v2. Trigger fire, enqueue, and briefing all worked; the failed creates stayed pending_create and self-healed after Step 18.

### Step 18: Migrate Todoist integration to unified API v1
- **Status**: complete
- **What it does**: Todoist sunset the REST v2 API (all calls return 410 Gone as of July 2026). Migrate daily_sync.py to the unified v1 API at https://api.todoist.com/api/v1: GET /projects is now cursor-paginated ({"results": [...], "next_cursor"}), task create/update/close keep the same endpoints and body fields under the new base URL, and the completion flag on GET /tasks/{id} is handled as checked OR is_completed for safety. Verified empirically against the live API before coding.
- **What good looks like**: The three pending_create items (Todoist Sync Test + step, Summer Fungicide Watch) create successfully in a "Yard" project; todoist_sync rows flip to synced with task ids stored.
- **Test**: Pure-logic tests with a stubbed requests object: project pagination search, create-when-missing, and completion-flag parsing. Live verification via in-container sync run.
- **Builds on**: Step 3
- **Notes**: No stored todoist ids predate the migration (all rows were pending_create), so it's a clean cutover with no id-format migration. Built 2026-07-03 and verified live: all three pending items created in Todoist (Yard project, group prefixes intact), sync rows synced with v1 ids. Also removed the unused todoist-api-python dependency from sync/requirements.txt and register.sh's check -- the code uses raw requests, and the stale import check was aborting register.sh before cron registration. Tests in tests/test_todoist_v1.py.

### Step 19: Harden against duplicate cron runs
- **Status**: awaiting verification (single fire on 2026-07-04 morning)
- **What it does**: The 2026-07-03 cron fired twice (06:00 UTC and 06:00 America/Chicago), producing duplicate same-day weather rows -- which broke the one-row-per-day assumption behind sustained_days and made the fungicide trigger fire a day early. Two fixes: (a) weather pull becomes a same-local-day upsert (second run refreshes the existing row instead of inserting), making the pipeline idempotent under double runs; (b) recreate both Hermes cron jobs so next_run is computed fresh under the container's current TZ (the stale job records predate the TZ env being set).
- **What good looks like**: Running the sync twice in one day leaves exactly one weather row per location with the freshest values. Cron fires once daily at 6:00 AM local.
- **Test**: Upsert function tested directly (insert then update path, one row remains). Cron single-fire observed on the next morning run.
- **Builds on**: Steps 3, 16
- **Notes**: The upsert guard also removes the manual-cleanup caveat from Step 16 -- ad-hoc verification runs now refresh instead of duplicate. Built 2026-07-03: upsert_weather_row() live (verified: manual run refreshed today's row instead of duplicating), stale duplicate rows deleted, both cron jobs deleted and recreated with next runs at 06:00/06:15 -05:00. Watch 2026-07-04 morning: exactly one plan-sync + one briefing message expected.
