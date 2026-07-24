# Build Plan

## Product summary

Plan-state is a condition-aware activity orchestrator for personal life domains.
It stores structured plans in SQLite, evaluates triggers daily against weather
and calendar conditions, cascades dates through prep/follow-up chains, and
delivers actionable briefings via Telegram. Deployed as a capability registering
into a Hermes Agent instance (Gideon) on a Mac Mini.

v1 shipped 2026-07-21 with three domains (Yard, Garden, Hunting), a consolidated
engine (shared plansync/engine.py, derived conditions, DB on APFS with WAL), and
AI-agnostic peer access (Claude and Hermes use the same MCP server). Full v1
build history is archived in docs/archive/BUILD_PLAN_V1.md (33 steps, all
complete).

v2 restructures the system around four jobs in priority order: plan management
(CRUD), daily surface (actionable view), condition watching (triggers), and
state management (transitions with undo). The v1 architecture was built
trigger-first -- trigger_def is the most complex data structure, and trigger
evaluation the most complex code path. v2 inverts that: the plan hierarchy
(domain/activity/step) is the foundation, triggers are optional enrichment, and
all state changes go through explicit state machines with cascade reactors. See
the redesign rationale in the project doc (plansync-redesign.md).

## Steps

### Phase 1: State machine foundation

### Step 34: Add batch_id to activity_log
Status: complete
Notes: ALTER TABLE ADD COLUMN was sufficient (nullable, no CHECK change -- no
table rebuild). Added idx_activity_log_batch up front since Step 45's undo
queries "most recent batch". Migration run on the live DB 2026-07-24 via
`docker exec gideon-gateway` (210 existing entries left NULL). Container name
gotcha: Docker Desktop shows the compose project "gideon" as a group row; the
actual containers are gideon-gateway and gideon-dashboard. Regression tests in
tests/test_batch_id.py.
What it does: Adds a batch_id TEXT column to activity_log. All log_change calls within a single tool invocation or sync step share a batch_id (a uuid4 hex). This groups cascaded side effects (e.g. complete_activity logs the activity completion + N step completions + M dependency fires) into one reversible unit for undo.
What good looks like: log_change accepts an optional batch_id. Callers that produce multiple log entries in one operation pass a shared batch_id. Existing log entries have batch_id NULL (compatible).
Test: Migration applies cleanly. log_change with batch_id stores it. log_change without batch_id stores NULL. Verify the column is queryable (SELECT * FROM activity_log WHERE batch_id=?).
Builds on: v1 complete

### Step 35: Transition function and reactor in engine.py
Status: complete
Notes: Tables in engine.py: ACTIVITY_TRANSITIONS / STEP_TRANSITIONS with a
CONTEXT_TARGET sentinel for revert (target from context['to_status']) and a
callable resolver for trigger_fire (preparing if prep steps exist, else
active -- daily_sync's rule, now universal; v1's _complete_activity set fired
dependents to 'preparing' unconditionally). Valid no-op transitions (defer
while watching) apply and log nothing. transition() logs via context
batch_id/source/action/extra; react() handles activity_completed (prep
pending+due -> completed, follow_ups -> due at today+lead, dependency fires
at today+offset with cascade). cascade_step_dates gained batch_id
passthrough. engine.new_batch_id() added. Nothing calls this yet -- Step 36
wires it. Tests in tests/test_transition.py (33).
What it does: Defines two state machines (activity and step) as transition tables in engine.py. Adds a transition(conn, entity_type, entity_id, event, context=None) function that validates the transition, applies the status change, and returns a list of side-effect events. Adds a react(conn, events, batch_id) function that processes side effects: auto-completing prep steps on activity completion (pending AND due), promoting follow-up steps, firing dependency triggers, logging all changes with the shared batch_id. Invalid transitions raise ValueError with the current state and attempted event.
What good looks like: transition(conn, "activity", aid, "complete") updates the activity to completed, returns events for step cascade and dependency fire. react() processes those events, each producing further transitions if needed. No raw UPDATE ... SET status= anywhere in the cascade path.
Test: Unit tests on transition(): valid transitions succeed, invalid transitions raise. Unit tests on react(): activity completion cascades prep steps (both pending and due), promotes follow-ups with correct dates, fires dependencies with offset_days. Cascade creates log entries sharing a batch_id.
Builds on: Step 34

### Step 36: Migrate server.py to use transition()
Status: complete
Notes: _complete_activity collapsed to transition+react (~20 lines); response
keeps v1 keys and adds batch_id + prep_steps_completed. Both v1 bugs fixed:
'due' prep steps auto-complete, invalid completions (watching/completed)
rejected with the state named. _defer_activity: status via transition(defer),
trigger-field rewrite stays raw (not status columns), all entries share one
batch. _update_step: status changes map through _step_status_event() --
no-table moves (due->pending) now error instead of writing silently;
skipped/completed recover via revert. update_activity's raw status field is
untouched (out of scope; revert/undo lands in Step 45). Last utcnow() in
server.py removed. Tests in tests/test_transition_migration.py (14).
What it does: Rewrites _complete_activity, _update_step (status changes only), and _defer_activity to call transition() + react() instead of issuing raw status UPDATEs. Fixes two v1 bugs as a side effect: (1) complete_activity now handles steps with status='due' (the transition table defines (due, parent_complete) -> completed); (2) follow-up steps on completed activities are promoted to 'due' and remain visible because step visibility no longer depends on parent status (prep for Step 39). Also wires batch_id through all these paths so undo can group them.
What good looks like: Existing test suites pass. The two v1 bugs are fixed (new tests confirm). _complete_activity, _update_step, _defer_activity contain zero raw status UPDATE statements.
Test: Regression: all existing tests pass. New: complete an activity with prep steps in 'due' status -- they auto-complete (was broken). Complete an activity with follow-up steps -- they're promoted to 'due' with correct dates and their log entries share the activity's batch_id. Defer an activity -- status returns to 'watching', trigger_def rewritten, steps re-cascaded. Invalid transition (complete a 'watching' activity directly) -- rejected with error, not silently applied.
Builds on: Step 35

### Step 37: Migrate daily_sync.py to use transition()
Status: complete
Notes: evaluate_triggers fires via transition(trigger_fire) -- the
preparing-vs-active resolution now lives only in engine._trigger_fire_target.
One batch per fire (status change + step cascade revert together);
check_overdue promotes via transition(overdue) with one batch for the whole
pass. Overdue promotions are now logged (v1 wrote them silently);
trigger_fired/trigger_date remain raw column updates (not status). Tests in
tests/test_sync_transition.py (10).
What it does: Rewrites evaluate_triggers (trigger fire) and check_overdue (pending -> due promotion) in daily_sync.py to call transition() instead of raw UPDATEs. The sync pipeline now uses the same state machine as the MCP server -- a trigger fire in the cron and a manual completion in Telegram go through identical code paths.
What good looks like: Sync pipeline runs clean end-to-end. Overdue steps get their status set via transition(). Trigger fires go through transition(). All changes logged with batch_ids.
Test: Regression: existing sync tests pass. Trigger fire via transition() produces the same DB state as the old code. Overdue check via transition() produces the same results.
Builds on: Step 36

### Step 38: Kill plan-sync Telegram delivery
Status: not started
What it does: Change the plan-sync cron job's delivery from Telegram to local (file-only). The sync still runs at 6:00 AM, evaluates triggers, cascades dates, writes JSON output. The heartbeat message no longer goes to Telegram. Morning briefing (6:15) and evening nudge (5:00 PM) remain.
What good looks like: No 6:00 AM Telegram message. Briefing and nudge unaffected. Sync output JSON still written for briefing-context to read.
Test: Manual -- verify no Telegram message at 6:00, verify briefing at 6:15 still has full content.
Builds on: v1 complete (independent of Steps 34-37)

### Phase 2: Shared view layer

### Step 39: Create actionable_items SQL view
Status: not started
What it does: Adds a CREATE VIEW actionable_items to schema.sql and a migration to create it on the live DB. The view joins steps/activities/domains and filters to steps with status IN ('pending','due') and due_date <= date('now'). No filter on activity status -- step visibility is determined by the step's own state. Adds a companion function engine.get_actionable_items(conn, as_of_date=None, domain_id=None) that queries the view with optional filters.
What good looks like: SELECT * FROM actionable_items returns all steps that need attention regardless of parent activity status. Follow-up steps on completed activities appear when their due_date arrives. The engine function provides a Python interface with filtering.
Test: Seed a DB with activities in various statuses (watching, preparing, active, completed) with steps due today. View returns steps from all parent statuses. Follow-up step on a completed activity with due_date=today appears. Step with due_date=tomorrow does not appear. engine.get_actionable_items() matches raw view query.
Builds on: v1 complete (independent of Phase 1, but Phase 1 makes step visibility correct)

### Step 40: Migrate evening_nudge and briefing-context to the view
Status: not started
What it does: Rewrites evening_nudge.py's build_nudge() and briefing-context.py's "Due Today or Overdue" query to use the actionable_items view (or engine.get_actionable_items). briefing-context.py switches to engine.get_db() instead of its own connection. The "This Week" lookahead query in briefing-context also moves to a shared function or a parameterized view query. Both scripts produce identical output to before (same format, same ordering) but from the shared definition.
What good looks like: evening_nudge and briefing-context contain zero inline SQL for "what's due." Output format is unchanged. briefing-context imports from engine.
Test: Regression: evening_nudge output matches old output for same DB state. briefing-context output matches old output. briefing-context uses engine.get_db() (no local sqlite3.connect).
Builds on: Step 39

### Step 41: Migrate get_upcoming to the view
Status: not started
What it does: Rewrites _get_upcoming in server.py to use the actionable_items view for the "due now" portion and a parameterized query against the view for the lookahead window. Removes inline SQL from the MCP server's upcoming logic.
What good looks like: get_upcoming returns the same structure as before but built from the shared view. Adding a new filter condition to "what's actionable" changes it everywhere at once.
Test: Regression: get_upcoming output matches old output for same DB state. Overdue steps count matches view results.
Builds on: Step 39

### Phase 3: Plan management

### Step 42: Make trigger_type and trigger_def optional
Status: not started
What it does: Relaxes validation in _validate_activities to allow activities without trigger_type or trigger_def. An activity created without a trigger starts in 'active' status (it's decided work, not condition-gated). _insert_activity handles the no-trigger case: no conditions derived, no trigger_date computed, status defaults to 'active'. update_activity can add a trigger_def later, which changes status to 'watching' and derives conditions. Domain authoring skill updated to note that simple date-based items can be added without trigger machinery.
What good looks like: add_activities(domain_id, [{"name": "Mulch garlic bed"}]) creates an active activity with no trigger. Adding trigger_def later via update_activity transitions it to 'watching' and derives conditions. Existing trigger-required activities work unchanged.
Test: Add activity without trigger -- status 'active', no conditions, no trigger_date. Add trigger_def via update_activity -- status 'watching', conditions derived, trigger_date computed. Existing validation still catches invalid trigger_types and trigger_defs.
Builds on: Steps 35-37 (transition function defines what 'active' means)

### Step 43: Add delete_activity tool
Status: not started
What it does: New MCP tool delete_activity(activity_id, permanent=False). Default (soft delete): sets activity status to 'skipped' via transition(), skips all child steps, logs to activity_log. With permanent=True: deletes the activity, its steps, its conditions, and related log entries. Returns what was affected.
What good looks like: Soft-delete an activity -- status 'skipped', all steps 'skipped', disappears from actionable_items view. Undo (Step 45) can revert a soft-delete. Permanent delete removes all traces.
Test: Soft-delete: activity and steps move to 'skipped'. Actionable items view excludes them. Permanent delete: rows gone from all tables.
Builds on: Steps 35-37

### Step 44: Add add_step tool
Status: not started
What it does: New MCP tool add_step(activity_id, name, step_type, lead_days, description=None). Creates a step on an existing activity. Due date derived from parent's trigger_date via engine.step_due_date(). If the parent has no trigger_date, due_date is NULL (set manually via update_step or when a trigger_def is added to the parent). Logged to activity_log.
What good looks like: Add a prep step to an existing activity -- due date correctly computed as trigger_date - lead_days. Add a follow-up step -- due date is trigger_date + lead_days. Add a step to a no-trigger activity -- due_date NULL.
Test: Add step with trigger parent -- correct due date. Add step to no-trigger parent -- NULL due date. Parent trigger_date change cascades to the new step.
Builds on: v1 complete

### Step 45: Undo tool
Status: not started
What it does: New MCP tool undo(item_type=None, item_id=None). Without args: finds the most recent batch_id in activity_log and reverts all entries in that batch. With args: finds the most recent batch for that item. Revert = restore old_value for each log entry in the batch, in reverse order. Uses transition() for status reversals (the transition table defines (completed, revert) -> [prior state]). Logs the undo itself as an 'undo' action. Returns what was reverted.
What good looks like: Complete an activity (cascades to 5 steps + 1 dependency). Call undo(). Activity returns to prior status, 5 steps return to prior status, dependency returns to 'watching'. All reversals logged.
Test: Complete an activity with cascades. Undo. Verify all entities returned to prior state. Undo a step completion. Undo a deferral. Undo with no prior actions -- returns empty. Undo an undo -- not allowed (or returns to the post-action state; decide during build).
Builds on: Steps 34-37 (batch_id + transition function with 'revert' event)

### Phase 4: Declarative plan sync

### Step 46: Stable identity for activities (ref_name)
Status: not started
What it does: Adds a ref_name TEXT column to activities. Set at creation time (defaults to a slugified version of name if not provided). Immutable after creation -- renaming an activity (update_activity name=) does not change ref_name. Used by load_domain sync mode (Step 47) to match declared activities to existing DB rows across renames. Unique within a domain.
What good looks like: Activity created as "Sow Broccoli Indoors" gets ref_name "sow-broccoli-indoors". Renamed to "Sow Cabbage Indoors" -- ref_name unchanged. load_domain can match by ref_name to update the existing row instead of creating a duplicate.
Test: Create activity -- ref_name auto-generated. Rename -- ref_name unchanged. Duplicate ref_name in same domain -- rejected. Explicit ref_name at creation -- used as-is.
Builds on: v1 complete

### Step 47: Upgrade load_domain to sync mode
Status: not started
What it does: When load_domain receives a definition for a domain that already exists, it diffs the declaration against current DB state instead of rejecting. Activities matched by ref_name (or name if ref_name absent). Diff: new activities created, changed activities updated, activities in DB but not in declaration flagged (not auto-deleted). Steps matched by name within parent. Returns a diff summary. With dry_run=True, returns the diff without applying. With dry_run=False (default when domain exists), applies and returns what changed.
What good looks like: Edit a domain definition YAML, call load_domain. New activities appear, changed activities update, nothing is silently deleted. The diff summary shows exactly what would change before applying.
Test: Load a domain. Modify the definition (add activity, rename activity, change trigger_def, remove activity). Re-load. Verify: new activity created, renamed activity updated (matched by ref_name), trigger_def change applied, removed activity flagged but not deleted. dry_run returns diff without changes.
Builds on: Step 46

### Step 48: Refactor daily_sync into independent stages
Status: not started
What it does: Breaks daily_sync.py's main() into named functions with explicit inputs and outputs: pull_weather(conn) -> WeatherResult, evaluate_conditions(conn, weather) -> ConditionResult, evaluate_triggers(conn) -> TriggerResult, cascade_dates(conn) -> CascadeResult, check_overdue(conn) -> OverdueResult. Each stage is callable independently (useful for re-running trigger evaluation without re-pulling weather, or testing a stage in isolation). main() calls them in sequence and aggregates results into the summary.
What good looks like: Each stage function is importable and testable independently. Running evaluate_triggers alone (without pull_weather first) works if weather data already exists. The pipeline still runs end-to-end via main().
Test: Call each stage independently with a seeded DB. Verify outputs match the aggregated main() run. Verify pull_weather can be skipped when weather data exists.
Builds on: Step 37 (stages use transition() internally)
