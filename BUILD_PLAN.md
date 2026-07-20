# Build Plan

## Product summary

Plan-state is a condition-aware activity orchestrator for personal life domains. It stores structured plans in SQLite, evaluates triggers daily against weather and calendar conditions, cascades dates through prep/follow-up chains, and delivers actionable briefings via Telegram. Deployed as a capability registering into a Hermes Agent instance (Gideon) on a Mac Mini. v1 is in production with two domains (Yard, Garden). The current focus is hardening (removing dead code, consolidating duplicated logic, fixing schema gaps) and making the system AI-agnostic so Claude and Hermes are equal peers of the same engine.

## Steps
### Step 1: SQLite database and schema
Status: complete
What it does: 7-table schema (domains, activities, steps, conditions, weather_log, todoist_sync, activity_log) with indexes, constraints, WAL mode, foreign keys
What good looks like: init-db.py creates the database; schema.sql applied cleanly
Test: none
Builds on: nothing
Notes: Working. Database exists but is empty.


### Step 2: MCP server with 10 tools
Status: complete
What it does: stdio JSON-RPC MCP server exposing get_domains, get_domain_plan, create_domain, create_activity, update_activity, complete_activity, defer_activity, add_observation, get_upcoming, get_weather_current
What good looks like: Hermes can call all tools, create and query domain data
Test: none
Builds on: Step 1
Notes: Working. Auto-creates DB if missing. Bug: _create_domain logs item_type as "activity" instead of "domain".


### Step 3: Daily sync pipeline
Status: complete
What it does: 7-step deterministic cron job: weather pull, condition evaluation, trigger evaluation, date re-estimation, overdue check, Todoist sync, summary output
What good looks like: Runs daily at 6 AM, produces JSON summary, syncs tasks to Todoist
Test: none
Builds on: Steps 1-2
Notes: Working. Soil temp always NULL (OpenWeatherMap limitation). Runs but produces empty output since DB has no data.
2026-07-04 fixes from first live Todoist round-trip: (1) overdue check moved after Todoist sync so completions detected in the same run aren't reported overdue; (2) completion poll now reports polled completions in the summary (todoist_completed was always 0 for them); (3) poll skips plan items already completed/skipped locally, preventing daily re-poll/re-log of past completions. Regression tests in tests/test_poll_completions.py. Completions are detected at most once daily (6 AM poll).


### Step 4: Morning briefing pipeline
Status: complete
What it does: briefing-context.py reads sync output + DB state, briefing skill instructs LLM to generate human-readable briefing
What good looks like: Concise actionable briefing delivered to Telegram at 6:15 AM
Test: none
Builds on: Step 3
Notes: Working but empty output since no data exists.
2026-07-04 refinements from first real briefing: context script now feeds strict buckets — "Due Today or Overdue" (due <= today) and "This Week" (next 7 days only, dateless items excluded); skill rules tightened: priorities = due today/overdue only (these always exist in Todoist), one line per This-week item, 2-3 lines per domain then bundle, one line per location in Conditions watch, no fact repeated across sections. Length target 75-150 words.


### Step 5: Registration script
Status: complete
What it does: register.sh copies skills/scripts to Hermes data dir, initializes DB, installs pip deps, registers MCP server and cron jobs
What good looks like: Single command connects plan-state to a running Hermes instance
Test: manual
Builds on: Steps 1-4
Notes: Working. Needs to be run on Mac Mini with new two-repo layout.


### Step 6: Domain definition schema
Status: complete
What it does: A JSON schema defining a complete domain definition -- one domain with all its activities, steps, conditions, and triggers in a single document. This is the contract between any LLM (Hermes, Claude, etc.) and the system.
What good looks like: Schema validates realistic domain definitions (lawn care, garden, hunting). An LLM can produce a conforming document from a planning conversation. Schema catches common errors (missing required fields, invalid trigger types, bad lead_days).
Test: Write 2-3 example domain definitions (lawn care, garden) and validate them against the schema. Invalid examples should fail validation with clear error messages.
Builds on: Step 1
Notes: See PRD FR-16.1-16.3 for requirements. Keep the format close to what create_activity already accepts to minimize translation.


### Step 7: Bulk load MCP tool (load_domain)
Status: complete
What it does: A new MCP tool that accepts a complete domain definition (conforming to the schema from Step 6), validates it, and atomically creates the domain + all activities + all steps + all conditions in one transaction. Returns the created domain with all IDs assigned.
What good looks like: load_domain(definition) creates everything or rolls back on error. Validation errors return structured feedback an LLM can act on (field path, error type, message). Duplicate domain names are rejected.
Test: Load a valid lawn care definition and verify all rows created. Load an invalid definition and verify rollback (zero rows created) with actionable error.
Builds on: Steps 2, 6
Notes: Add to mcp-server/server.py alongside existing tools.


### Step 8: Domain authoring skill
Status: complete
What it does: A skill document (markdown) that teaches an LLM how to run a domain planning conversation and produce a valid domain definition. Covers: how to probe for trigger conditions and lead times, how to structure prep chains, how to format the output, and examples of complete definitions.
What good looks like: A user says "help me plan my fall garden" and the LLM produces a valid domain definition that can be passed directly to load_domain. The skill works with both Hermes (local LLM) and Claude.
Test: manual -- run the skill with a test domain conversation and verify the output validates against the schema
Builds on: Steps 6, 7
Notes: Should be portable across models. For Hermes/smaller models: more structured input, more examples, tighter constraints. See PRD FR-17.1.


### Step 9: Deploy and load first domain
Status: complete
What it does: Deploy the two-repo layout on Mac Mini, run register.sh, then use the authoring skill to create the first real domain (user's choice of lawn care, garden, or hunting).
What good looks like: Domain exists in DB, activities are in "watching" status, next morning's cron run pulls weather and evaluates conditions, Todoist shows tasks for any triggered activities.
Test: manual -- verify cron output JSON has real data, Todoist shows domain project with tasks
Builds on: Steps 5-8, 12-14
Notes: This is the first end-to-end validation with real data. Do Steps 12-14 first so the schema is final before real data exists (no migration needed on an empty DB). Completed 2026-07-02: Yard domain (14 activities, 5 groups) authored from user's local-conditions brief and loaded on the Mac Mini; definition kept at domains/yard.json. Verified end-to-end across 07-03/07-04: cron pulled real weather, fired Summer Fungicide Watch, created Todoist tasks (after the Step 18 API migration), delivered briefings. Marked complete 2026-07-19.


### Step 10: Load additional domains
Status: complete
What it does: Use the authoring skill to create 1-2 more domains, validating the workflow is repeatable and cross-domain features work (get_upcoming shows activities from multiple domains, Todoist has multiple projects).
What good looks like: Multiple domains in the system, morning briefing covers all of them, cross-domain upcoming view works.
Test: manual
Builds on: Step 9
Notes: Good time to fix the soil_temp gap -- either find an alternative data source or remove soil_temp triggers from domain definitions. Completed 2026-07-15: Garden domain loaded (Murfreesboro 6-section rotation, 46 activities, 55 steps, 41 calendar triggers + 5 dependency chains, grouped by bed); definition at domains/garden.json. Cross-domain features confirmed in daily operation: briefing covers both domains, Todoist has Yard and Garden projects, completions polling back from both (07-13 through 07-18 log entries). soil_temp fix now handled by Step 23. Marked complete 2026-07-19.


### Step 11: Fix known bugs
Status: complete
What it does: Fix the _create_domain item_type bug (logs "activity" instead of "domain"), consolidate the duplicate DB creation paths (ensure_db in server.py vs init-db.py).
What good looks like: Activity log correctly attributes domain creation. Single canonical DB initialization path.
Test: Create a domain via MCP, verify activity_log row has item_type="domain". Verify only one path creates the DB.
Builds on: Step 2
Notes: Fixed. Removed ensure_db() from server.py (DB must be created by init-db.py or register.sh). Fixed _create_domain log_change to use item_type="domain".


### Step 12: Activity grouping
Status: complete
What it does: Adds a free-form group_name TEXT column to activities for within-domain bundling (crop name, garden bed, food plot, etc.). Carries no trigger logic -- display and organization only. Supported in the domain definition schema, load_domain, create_activity, update_activity, get_domain_plan, and get_upcoming. briefing-context.py groups activities by it. Todoist sync uses it in task naming or as a section so bundles read together.
What good looks like: A garden domain can have "Start Tomato Seeds", "Transplant Tomatoes", and "Tomato Harvest Watch" all under group "Tomatoes"; get_upcoming and the morning briefing present them as one bundle. Activities without a group behave exactly as today.
Test: Load a domain definition with grouped and ungrouped activities; verify group_name persists, get_domain_plan and get_upcoming return it, and briefing context output groups by it.
Builds on: Steps 6, 7
Notes: Rationale: the bundling layer between domain and activity (plant type, species, bed) is not one fixed taxonomy, so it's a free-form field rather than a table. Domain = one location/weather context; dependency chains + group_name handle bundling within it. Built 2026-07-02: column named group_name (not group -- SQL keyword). Todoist tasks are prefixed "Group: Task" via task_content() in daily_sync.py; steps inherit the group from their parent activity. Local plansync.db (empty, gitignored) was deleted and re-initialized from the updated schema. Mac Mini DB re-init happens at Step 9 deploy. Regression tests in tests/test_group_name.py (10 tests); the Todoist naming test skips locally without requests installed.


### Step 13: Amend-domain MCP tool (add_activities)
Status: complete
What it does: A new MCP tool that adds one or more activities (with steps and conditions) to an existing domain, using the same activity-definition format as load_domain. Validates like load_domain, atomic (all-or-nothing), and resolves dependency activity_ref names against BOTH the incoming batch and activities already in the domain -- so a new "Transplant Tomatoes" can depend on an existing "Start Tomato Seeds".
What good looks like: add_activities(domain_id, activities=[...]) creates everything or rolls back with structured errors. Duplicate activity names within the domain are rejected. New activities start in "watching" status and are picked up by the next cron run with no special handling.
Test: Load a domain, then add an activity whose dependency trigger references a pre-existing activity by name; verify resolution to the correct ID. Add an invalid batch; verify rollback (zero new rows) and actionable errors.
Builds on: Steps 7, 12
Notes: load_domain stays create-only. Existing update_activity/complete_activity/defer_activity already cover editing; this fills the "grow an existing domain" gap. Built 2026-07-02: activity insert logic extracted into shared _insert_activity() used by both load_domain and add_activities; validation generalized via _validate_activities(existing_names). sort_order for new activities continues after the domain's current max. Regression tests in tests/test_add_activities.py (14 tests). Building this surfaced the pending_create gap fixed in Step 15.


### Step 14: Domain authoring skill v2 (create + amend)
Status: complete
What it does: Updates skills/domain-authoring.md to manage domains over their lifetime, not just create them. Adds: (1) amend mode -- when the user names an existing domain, fetch it with get_domain_plan, run the same probing for just the new activities, call add_activities; (2) domain-scoping guidance -- a domain is one location/weather context and a coherent plan (Garden, Yard, TN Hunting Prop 1), not a broad life category; (3) the activity-vs-step rule -- if it needs its own trigger (date, weather, or "after X completes") it's an activity, if it's a fixed-offset chore around a triggered event it's a step; (4) group_name guidance with a multi-phase crop example (tomatoes as a 3-activity dependency chain under one group).
What good looks like: "Add tomatoes to my garden" produces grouped, dependency-chained activities added to the existing Garden domain via add_activities. "Help me plan my garden" still produces a fresh load_domain call. The skill picks the right mode without being told.
Test: manual -- run one create conversation and one amend conversation; verify the amend path calls get_domain_plan first and produces a valid add_activities payload referencing an existing activity
Builds on: Steps 8, 12, 13
Notes: Single skill file for both modes so the trigger-format reference isn't duplicated. Built 2026-07-19, approved on the strength of validator checks (example payloads verified against server._validate_domain_definition / _validate_activities, including a dependency ref resolving to a pre-existing domain activity). Beyond spec: the conditions-array rule is now an explicit bold rule (was only implied by the example -- the fall-garden bug vector) and the recurrence probe was dropped from the conversation flow (field is never read; Step 23 drops the column). Regression: tests/test_authoring_skill_examples.py extracts the JSON examples from the skill file itself and validates them -- when Step 22 changes validation, it fails until the skill is updated in lockstep. Manual create/amend conversation test deferred to first real use.


### Step 15: Todoist enqueue reconciliation
Status: complete
What it does: Fixes a v1 gap: nothing ever writes pending_create rows to todoist_sync, so no task would ever be created in Todoist. Adds a reconciliation pass in daily_sync.py just before the Todoist step: enqueue pending_create for (a) any activity in status preparing/active with no todoist_sync row, and (b) any pending/due step with a due_date whose parent activity is preparing/active and which has no todoist_sync row. Idempotent -- catches status changes from any source (cron trigger fire, Hermes tools, Todoist completion polling).
What good looks like: After a trigger fires, the next sync run creates Todoist tasks for the activity and its steps. Running the sync twice does not enqueue duplicates. Completed/skipped items are never enqueued.
Test: Seed a DB with a preparing activity + steps, run the reconciliation function, verify pending_create rows exist and are correct; run again, verify no duplicates; verify watching/completed activities and completed steps are not enqueued.
Builds on: Step 3
Notes: Found while building Step 13. Reconciliation in the cron (rather than enqueue calls at every status-change site) fits the deterministic-pipeline design and self-heals missed enqueues. Must land before Step 9, whose verification requires tasks appearing in Todoist. Built 2026-07-02: enqueue_todoist_items() runs as its own pipeline step before todoist_sync, so the queue fills even when TODOIST_API_KEY is unset. Also made the requests import guarded so sync code is importable in test environments without network deps. Tests in tests/test_todoist_enqueue.py (6 tests).


### Step 16: Derive daily high/low from forecast
Status: complete
What it does: Fixes a trigger-correctness bug: the weather pull stores the current-weather snapshot's temp_max/temp_min, which at a single reading are both ~equal to the instantaneous temp. A 6 AM cron run records the morning temp as the day's "high", so triggers like daily_high <= 85 fire on cool mornings regardless of afternoon heat. Fix: derive daily_high/daily_low from the 3-hourly forecast already fetched each run -- group forecast entries by LOCAL calendar day (city.timezone offset; entries are UTC), take max/min of today's temps, blend with the current reading (max for high, min for low). Falls back to the current reading if no forecast entries remain for today.
What good looks like: weather_log rows show a realistic spread (e.g. high 97 / low 70, not 91/91). A morning run correctly represents the coming afternoon peak, so "is today a <=85 day" triggers fire the morning of a qualifying day.
Test: Pure function derive_daily_range(current_temp, forecast_data, now_utc) tested against a canned forecast payload: blending in both directions, UTC-to-local day boundary (00:00 UTC entry belongs to the previous local day in UTC-5), and the no-entries-left fallback.
Builds on: Step 3
Notes: Zero new API calls or dependencies -- uses the forecast response already stored in forecast_json. Chosen over One Call daily summary (separate subscription) and a second evening cron run (still a snapshot, misses the peak). A 6 AM trigger decision about "today" should use the forecast anyway: the observed high isn't knowable until evening. Built 2026-07-02: verified live in-container -- old snapshot row 90.97/90.97 vs derived 88.1/78.8. Tests in tests/test_weather_range.py (9 tests). Caveat recorded: weather_log assumes one row per location per day (sustained_days reads the last N rows); manual sync runs create duplicates, so clean up extra same-day rows after ad-hoc verification runs.


### Step 17: Early Todoist validation task
Status: complete
What it does: Adds a throwaway "Todoist Sync Test" activity (group "System") to the Yard domain with a calendar trigger of 2026-07-03 and one follow-up step, loaded via the add_activities tool (dogfooding Step 13 against the live DB). Tomorrow's 6 AM cron should: fire the trigger (no prep steps -> status active), enqueue both the activity and its step via the Step 15 reconciliation, and create two Todoist tasks in the Yard project with the "System: " group prefix. Completing them in Todoist then exercises the completion-polling path on the following run.
What good looks like: Two tasks in Todoist by ~6:05 AM on 2026-07-03: "System: Todoist Sync Test" and "System: Confirm test tasks appeared, then complete both". Validates trigger fire -> enqueue -> task creation -> (on completion) poll-back, without waiting for the fungicide trigger ~July 5.
Test: manual -- observe Todoist tomorrow morning; after completing the tasks there, confirm the activity shows completed in the DB the following day
Builds on: Steps 9, 13, 15
Notes: Cleanup: after verification, the activity is already completed via the Todoist poll; no deletion needed (completed activities are inert). Validates the full loop early. 2026-07-03: task creation failed with 410 Gone -- Todoist sunset REST v2. Trigger fire, enqueue, and briefing all worked; the failed creates stayed pending_create and self-healed after Step 18. Verified 2026-07-19 against the live DB: activity and its step both status=completed with completed_at 2026-07-04T11:00 (06:00 local) and activity_log status_change entries with source "todoist" -- the full trigger fire -> enqueue -> task creation -> completion poll-back loop worked. Subsequent todoist-sourced completions on 07-13, 07-16, 07-18 confirm the poll path kept working for real activities.


### Step 18: Migrate Todoist integration to unified API v1
Status: complete
What it does: Todoist sunset the REST v2 API (all calls return 410 Gone as of July 2026). Migrate daily_sync.py to the unified v1 API at https://api.todoist.com/api/v1: GET /projects is now cursor-paginated ({"results": [...], "next_cursor"}), task create/update/close keep the same endpoints and body fields under the new base URL, and the completion flag on GET /tasks/{id} is handled as checked OR is_completed for safety. Verified empirically against the live API before coding.
What good looks like: The three pending_create items (Todoist Sync Test + step, Summer Fungicide Watch) create successfully in a "Yard" project; todoist_sync rows flip to synced with task ids stored.
Test: Pure-logic tests with a stubbed requests object: project pagination search, create-when-missing, and completion-flag parsing. Live verification via in-container sync run.
Builds on: Step 3
Notes: No stored todoist ids predate the migration (all rows were pending_create), so it's a clean cutover with no id-format migration. Built 2026-07-03 and verified live: all three pending items created in Todoist (Yard project, group prefixes intact), sync rows synced with v1 ids. Also removed the unused todoist-api-python dependency from sync/requirements.txt and register.sh's check -- the code uses raw requests, and the stale import check was aborting register.sh before cron registration. Tests in tests/test_todoist_v1.py.


### Step 19: Harden against duplicate cron runs
Status: complete
What it does: The 2026-07-03 cron fired twice (06:00 UTC and 06:00 America/Chicago), producing duplicate same-day weather rows -- which broke the one-row-per-day assumption behind sustained_days and made the fungicide trigger fire a day early. Two fixes: (a) weather pull becomes a same-local-day upsert (second run refreshes the existing row instead of inserting), making the pipeline idempotent under double runs; (b) recreate both Hermes cron jobs so next_run is computed fresh under the container's current TZ (the stale job records predate the TZ env being set).
What good looks like: Running the sync twice in one day leaves exactly one weather row per location with the freshest values. Cron fires once daily at 6:00 AM local.
Test: Upsert function tested directly (insert then update path, one row remains). Cron single-fire observed on the next morning run.
Builds on: Steps 3, 16
Notes: The upsert guard also removes the manual-cleanup caveat from Step 16 -- ad-hoc verification runs now refresh instead of duplicate. Built 2026-07-03: upsert_weather_row() live (verified: manual run refreshed today's row instead of duplicating), stale duplicate rows deleted, both cron jobs deleted and recreated with next runs at 06:00/06:15 -05:00. Verified 2026-07-19 against the live DB and sync-output/: zero duplicate location/day rows in weather_log (18 rows, 18 distinct location-days), exactly one weather row per day for every day 2026-07-04 through 2026-07-19, and one sync summary JSON per day with mtimes at ~06:00 daily since 07-05 (no later-in-day rewrite that a second fire would leave). 16 consecutive single-fire days.


### Step 20: Honest sync heartbeat (errors visible in Telegram)
Status: complete
What it does: Fixes an observability lie: is_empty() and to_stdout() in daily_sync.py ignore summary.errors, so a run where only errors happened (dead weather key, API outage) delivers "ran clean, no changes" to Telegram while the errors go to stderr. Change: the stdout heartbeat always reports error count and a one-line summary of each error; a run with errors never claims clean. The daily Telegram message is the system's only dashboard, so it must be truthful.
What good looks like: A run with a bad OPENWEATHERMAP_API_KEY produces a Telegram message that says errors occurred and names them. A genuinely clean run still produces the short "ran clean" heartbeat.
Test: Unit tests on to_stdout(): errors-only summary → output contains error count and text, not "ran clean"; empty summary with no errors → unchanged heartbeat; errors alongside real changes → both reported.
Builds on: Step 3
Notes: ~10 lines. Do first — it affects trust in the running system today and every later step benefits from honest failure reporting. Built and approved 2026-07-19: "ran clean" now requires no changes AND no errors; errors append an "errors: N" section (first line of each, so tracebacks don't balloon the Telegram message). stderr/exit-code behavior unchanged. Live immediately via the volume mount. Tests in tests/test_sync_heartbeat.py (6 tests).


### Step 21: Remove Todoist integration
Status: complete
What it does: Removed Todoist as a task surface; Telegram/Hermes chat is the sole interface. Evening nudge cron replaces Todoist's nag function.
What good looks like: Sync pipeline has zero Todoist references. Evening nudge fires only on days with open due items.
Test: Pipeline runs clean end-to-end with no Todoist code or key. Nudge script unit-tested.
Builds on: Steps 3, 15, 18
Notes: Verified 2026-07-20: zero Todoist references in server.py, daily_sync.py, schema.sql, register.sh, or any skill. evening_nudge.py exists and is registered. The todoist_sync table may still exist in the live DB as an orphan -- Step 25's migration drops it. Todoist references remain only in historical BUILD_PLAN notes.

## Remaining steps
Two parallel tracks, then a consolidation pass.
Track A -- Engine hardening: 28 → 22 → 23 → 25 (consolidate code, then fix logic, then clean dead surface, then migrate schema)
Track B -- AI-agnostic access: 27 → 30 → 31 (register Claude as peer, add skill, add dossier export)
Then: 26 (doc consolidation, after both tracks complete)
27 and 28 have no dependencies on each other and can start simultaneously. 30 can proceed independently from 22/23.

### Step 27: AI-agnostic access (source attribution + Claude MCP registration)
Status: complete
What it does: Two changes that make the system agent-neutral. (1) Open the source enum in activity_log: currently CHECK(source IN ('cron','hermes')) -- change to allow 'claude' and 'human'. Pass client identity into the MCP server via a PLANSYNC_CLIENT env var (defaults to 'hermes'; Claude desktop config sets it to 'claude'). log_change reads the env var instead of hardcoding 'hermes'. (2) Register the same MCP server in Claude desktop: add a claude_desktop_config.json entry pointing at docker exec -i gideon-gateway python /opt/plansync/mcp-server/server.py. Zero new code -- Claude gets the same tools Hermes has, all writes stay container-side (no mount-locking issues), and both agents are peers of the same engine.
What good looks like: Claude desktop lists all plansync tools. Creating an activity from Claude logs source='claude' in activity_log. Creating from Hermes still logs 'hermes'. The DB is written only from inside the container regardless of which agent initiated the call.
Test: Call load_domain from Claude desktop, verify activity_log row has source='claude'. Call from Hermes, verify source='hermes'. Verify both writes succeed without locking errors.
Builds on: Step 2
Notes: Do this first -- it unblocks the operational workflow problem (Claude sessions can read and write live state instead of talking about it in conversation and hoping it gets transcribed). Provide a sample claude_desktop_config.json snippet in the repo README or a dedicated docs/claude-setup.md. The docker exec approach means the server process lifecycle is tied to each tool call (starts, serves, exits) rather than running persistently -- acceptable for interactive use; if latency matters later, a persistent stdio wrapper is a small addition.
Built 2026-07-20. Plan correction: the original note claimed the schema CHECK change was compatible with the current DB -- wrong for new inserts (SQLite enforces the live table's stored CHECK on every insert), so scripts/migrate-source-enum.py rebuilds activity_log with the widened constraint (idempotent, row-count-verified, transactional). log_change resolves its default source from PLANSYNC_CLIENT at call time (explicit source arg still wins); cron path untouched. Setup documented in docs/claude-setup.md. Verified live end-to-end 2026-07-20: migration applied to the live DB (128 rows intact), plansync registered in Claude desktop on the Mac Mini via docker exec with PLANSYNC_CLIENT=claude, add_observation from a Claude session logged source='claude' while prior hermes/cron rows were unchanged. Regression tests in tests/test_source_attribution.py (6 tests).


### Step 28: Extract shared engine module
Status: not started
What it does: Cascade logic (cascade_step_dates / _cascade_steps) and trigger-date computation (compute_trigger_date) are duplicated between server.py and daily_sync.py -- same algorithm, two files, inevitable drift. Extract into a shared plansync/engine.py module imported by both. Includes: cascade_step_dates, compute_trigger_date, log_change, get_db, and row_to_dict. Both server.py and daily_sync.py import from the shared module instead of maintaining their own copies.
What good looks like: Zero duplicated domain logic between server.py and daily_sync.py. A change to cascade behavior is made once, tested once, and both code paths use it. The shared module is importable from tests without starting the MCP server.
Test: Existing regression suites pass with imports redirected. Add a test that verifies server.py and daily_sync.py contain no local definitions of the extracted functions.
Builds on: Steps 2, 3
Notes: Do before Step 22 so conditions-derivation logic lands in the shared module from the start, not as a later refactor. The volume mount means the shared module is live-editable like everything else.


### Step 22: Conditions derivation + tool consolidation
Status: not started
What it does: Two related changes, done together because both rewrite validation logic and skill docs. (1) Conditions derived from trigger_def: authoring supplies only trigger_def; load_domain, add_activities, and update_activity generate conditions rows by walking compound trees for condition-type leaves. The conditions table remains as an evaluation cache. Validation rejects old-format definitions that include an explicit conditions array. (2) Retire create_domain and create_activity: these predate load_domain/add_activities and offer a weaker authoring path (no validation, no ref resolution, no atomicity). Remove them; a single-activity addition is add_activities with a one-element array. Tool list drops from 12 to 10. Update domain_schema.json, skills/domain-authoring.md, skills/plansync.md, CLAUDE.md.
What good looks like: A condition/compound activity authored with only trigger_def gets correct conditions rows and fires when weather qualifies. One authoring path for creation (load_domain / add_activities), one for modification (update_activity / complete_activity / defer_activity). Skills document exactly one way to do each thing.
Test: Load a domain with condition and compound activities (no conditions arrays) -- derived rows match trigger_def leaves; condition evaluation against seeded weather fires triggers. Old-format definition with conditions array -- rejected with actionable error. update_activity changing trigger_def -- conditions rows re-derived. Server lists 10 tools; removed names return unknown-tool.
Builds on: Steps 7, 13, 28
Notes: Chose derive-at-write over evaluate-straight-from-trigger_def-and-drop-the-table: keeping the cache table preserves is_met/current_value visibility for get_domain_plan and the briefing at no authoring cost. Existing live rows (Yard/Garden) already have hand-authored conditions; Step 25's migration re-derives them from trigger_def and verifies parity as a consistency check. Derivation logic lives in engine.py (from Step 28).


### Step 23: Remove dead and trap surface
Status: not started
What it does: Five verified write-only or dead-end features removed or closed:
(a) recurrence -- stored on activities, never read by the sync; recurring activities do not actually recur. Drop the column and all code/schema/skill references. Convention instead: annual backbones are re-authored via a yearly LLM conversation (fits the LLM-plans/cron-executes split better than a recurrence engine).
(b) steps.condition -- stored, never evaluated. Drop the column and references.
(c) add_observation -- currently write-only. Keep the tool but close the loop: briefing-context.py prints observations from the last 7 days so field notes surface in the next morning's briefing.
(d) soil_temp -- OWM supplies no soil temperature; any trigger using it silently never fires. Remove from eval and schema; validation rejects metric: soil_temp with an error suggesting daily_high.
(e) deferred dead-end -- defer_activity sets status='deferred', but evaluate_triggers only scans 'watching', so a deferred activity never fires again; check_overdue has no parent-status filter, so steps of deferred/completed activities generate perpetual noise. Fix: defer_activity keeps status='watching' and just sets the new trigger_date + logs the reason; drop 'deferred' from the status enum; add parent-status filter to check_overdue.
What good looks like: Schema, tools, and skills describe only behavior that actually executes. A deferred activity fires on its new date. Overdue lists contain only steps of live activities.
Test: defer an activity -- status watching, new date, cascaded steps, fires on new date. check_overdue with a skipped parent -- step not reported. load_domain with soil_temp metric -- rejected. Observation added -- appears in briefing-context output within the 7-day window.
Builds on: Steps 3, 22
Notes: Column drops land in the live DB via Step 25's migration; until then the code simply stops reading/writing the dead fields (compatible with the current schema).


### Step 25: Database migration and relocation
Status: not started
What it does: One migration script (migrate-db.py) that applies every schema change from Steps 21-23 to the live DB and moves it off the exFAT/VirtioFS mount. Also adds a weather_date TEXT column with UNIQUE(location, weather_date) to enforce the one-row-per-day invariant at the schema level (replacing the CLAUDE.md convention and simplifying the upsert to INSERT ... ON CONFLICT ... DO UPDATE). Migration is rebuild-and-copy: create new DB at the new path from updated schema.sql, copy all rows (activities minus recurrence, steps minus condition, todoist_sync dropped, 'deferred' statuses remapped to 'watching'), re-derive conditions rows from trigger_def and verify parity with hand-authored rows, verify row counts. Old file preserved as backup. Once off exFAT, journal mode returns to WAL.
What good looks like: Sync pipeline and MCP server run clean against the migrated DB; row counts match; Yard and Garden domains fully intact; weather upsert uses ON CONFLICT.
Test: Run migrate-db.py against a copy of the live DB -- per-table row counts match, derived conditions match originals, daily_sync.py completes clean. Duplicate weather insert for same location+day either upserts or raises IntegrityError. Manual: one overnight cron cycle on the migrated DB.
Builds on: Steps 21, 22, 23
Notes: Must be the LAST schema-touching step. The weather_date column exists because SQLite does not support expression indexes on date() directly in all versions, so a computed UNIQUE(location, date(recorded_at)) is not portable; the TEXT column with an application-set value is the fallback. Deploy actions: (1) pause 6 AM crons or run after the morning cycle, (2) run migrate-db.py in-container, (3) set PLANSYNC_DB to the new path in gideon config/compose env, (4) update default DB_PATH in server.py, daily_sync.py, briefing-context.py, init-db.py, and init/backup paths in register.sh, (5) restart container so the MCP server picks up the new path, (6) verify with manual sync run + hermes chat tool call, (7) after one clean overnight cycle, archive old plansync.db. Update CLAUDE.md: journal-mode convention (WAL allowed again at the new location) and volume-mount notes.


### Step 30: Domain authoring Claude skill
Status: not started
What it does: Port skills/domain-authoring.md as a Claude skill so authoring conversations in Claude desktop and Cowork follow the same rules as in Telegram. Nearly verbatim from the Hermes version -- same conversation flow, trigger-format reference, validation rules -- adapted for Claude's skill format. Requires Step 27 so the MCP tools are available.
What good looks like: User says "help me plan my hunting season" in Claude desktop. Claude runs the same probing conversation, produces a valid domain definition, calls load_domain or add_activities via the MCP server. The activity_log shows source='claude'. The domain appears in the next morning's briefing with no manual transcription.
Test: manual -- run one create and one amend conversation in Claude desktop; verify activities are in the DB, attributed to 'claude', and appear in get_upcoming.
Builds on: Steps 14, 27
Notes: Drift risk from maintaining two copies. If formats are compatible enough, keep one file and symlink into both agent directories. Otherwise extract shared trigger-reference.md.


### Step 31: Dossier export and project sync
Status: not started
What it does: A new script export_dossier.py that reads the DB and produces a markdown file per domain: current activities with status and estimated dates, recent completions and observations (last 14 days), active conditions, recent weather. Output to docs/dossiers/ in the repo. Refresh paths: (a) the 6 AM cron calls it after daily_sync.py; (b) a Cowork scheduled task stages the files and project_writes them to the claude.ai project. Hard rule: dossier docs are never hand-edited.
What good looks like: A new Claude chat session reads yard/state.md and knows exactly what's active, what fired recently, what's coming up -- no tool calls or conversation history needed. Matches the DB within 24 hours.
Test: Run export_dossier.py against the live DB; verify output contains all active activities, recent completions, weather. Verify round-trip through project_write/project_read.
Builds on: Steps 3, 27
Notes: Does not replace MCP tools for live queries. Its value is bootstrapping context for sessions without MCP access (mobile, web chat) or quick orientation before deeper tool calls.


### Step 26: Documentation consolidation
Status: not started
What it does: Collapses overlapping state documents. CLAUDE.md stays as conventions + structure. BUILD_PLAN.md becomes the only live state doc -- absorb anything still true from STATUS.md, then archive STATUS.md. Remove the "Read STATUS.md first" convention. Delete every doc section that restates something the code already says (tool counts, table counts, file inventories). Docs carry only what code can't: intent, conventions, decisions.
What good looks like: A fresh session needs exactly two files (CLAUDE.md, BUILD_PLAN.md) to be fully oriented, and nothing in either contradicts the code.
Test: manual -- read-through: no stale claims, no restated code facts, no reference to archived docs as live.
Builds on: All previous steps
Notes: Do last so the consolidated docs describe the post-cleanup system once, not incrementally.