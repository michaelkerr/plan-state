# Roadmap

## Product summary

PlanSync is a condition-aware activity orchestrator for personal life domains — yard care, gardening, hunting. It stores structured plans in SQLite, evaluates weather triggers hourly, cascades dates through prep/follow-up chains, and delivers briefings via Telegram. Deployed as a capability inside a Hermes Agent instance (Reach) on a Mac Mini. Three domains in production.

## What's built

- **Plan store**: domains, activities with trigger definitions (calendar, condition, dependency, compound), steps with cascading dates, weather-condition evaluation cache, source-attributed activity log with batch-grouped undo
- **MCP server**: 15 tools for plan CRUD — load/sync domains, add/update/complete/defer/delete activities, add/update steps, undo, observations, upcoming view, weather queries. Shared by Hermes and Claude as peer agents. Error responses use `isError` flag for proper MCP protocol signaling
- **Hourly sync pipeline**: deterministic (zero LLM tokens) — weather pull, condition evaluation, trigger firing, date cascade, overdue promotion. Five independent stages, each callable alone
- **Telegram surfaces**: LLM morning briefing at 6:15, deterministic evening nudge at 5 PM (silent when clear)
- **State machines**: all status changes route through transition tables with a cascade reactor; batch_id groups operations for undo
- **Authoring module**: validation, insertion, sync, and ref resolution extracted to plansync/authoring.py — testable without MCP, reusable from future CLI
- **Declarative plan sync**: load_domain diffs declarations against DB state, creates/updates/flags without deleting
- **Dossier export**: per-domain markdown state files for sessions without MCP access

## Now

### Briefing verbosity
- **Type**: improvement
- **What it does**: The morning briefing is too verbose. The problem likely originates upstream — plans have too many activities/steps for what's actually useful day-to-day, and the briefing context dumps everything into LLM prompt without filtering for signal. Diagnose where the noise comes from (plan bloat vs. context dump vs. LLM summarization) and fix the root cause.
- **Done when**: Morning briefing consistently fits in a quick phone-screen read. Only items that need attention today or this week appear.
- **Touches**: sync/briefing_context.py, skills/plansync-briefing.md, possibly the domain definitions in /opt/data/plansync/domains/
- **Risk**: Trimming context may cause the briefing to miss items the user cares about. Test with real domain data before deploying.
- **Notes**:

### Easier completions
- **Type**: improvement
- **What it does**: Completing an activity requires too much typing and one or more LLM round-trips (user says "done with X" → agent parses → agent calls complete_activity). Reduce the friction — faster identification of the activity, fewer steps to confirm.
- **Done when**: The user can close a common task in under 10 seconds from Telegram with at most one confirmation.
- **Touches**: skills/plansync.md (Hermes skill), mcp-server/server.py (possibly a fuzzy-match or shorthand tool), sync/evening_nudge.py (could include inline completion hints)
- **Risk**: Shorthand matching could misidentify activities. Need to confirm before acting.
- **Notes**:

### Architecture visualization — DONE
- **Type**: infrastructure
- **Notes**: Published as interactive artifact. Component map with click-for-details, daily cron timeline, four expandable data-flow walkthroughs (sync, completion, authoring, undo). Dark-mode aware. https://claude.ai/code/artifact/9908c269-1654-4c07-a218-a8bd0e4e1974

## Next

- **Plan audit and trim** (improvement): Review the three live domain definitions for activities/steps that are noise. Too many items make the briefing verbose and the completion list overwhelming. Trim or consolidate.
- **Calendar/timeline view** (feature): A visual view of upcoming activities across domains — calendar or timeline format. Probably a published artifact reading from dossier or DB export.
- **Completion from nudge** (improvement): The evening nudge lists open items but offers no fast path to close them. Add inline completion suggestions or a numbered shorthand.

## Later

- **Step-level completions in nudge**: The nudge shows steps but completions are activity-level. Surfacing step completion would reduce the "everything is still open" noise.
- **Weather trend visualization**: Historical weather data is logged but never surfaced. A chart of temps over time would help with manual trigger decisions.
- **Sync pipeline observability**: No visibility into whether the hourly cron is actually running and what it's doing. A health check or dashboard would catch silent failures.

## Parked

- **Todoist integration**: Removed 2026-07-19. ~300 lines + fragile API dependency for a once-daily completion poll. Conversational completion is better in every way. Would only revisit if Telegram stops being the primary surface.
- **v2 federated signal/boundary agents**: Archived design (docs/archive/v2-signals-boundaries-prd.md). A more elaborate agent architecture that was shelved in favor of the simpler plan-management-first v2. Revisit only if a full season of operation surfaces a concrete limitation.
- **Recurrence**: Explicitly unsupported (validation rejects it). Annual plans are re-authored each season via a planning conversation. Revisit only if the re-authoring workflow proves too heavy.
