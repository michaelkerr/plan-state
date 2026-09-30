# Roadmap

## Product summary

dispatch is a condition-aware task system for personal life domains — lawn, garden, hunting, home. Reusable YAML path templates are instantiated into items with triggers; an hourly deterministic job evaluates weather and fires them; Telegram briefings carry one-code completions ("done G1"). Runs as the `reach-plansync-new` container next to Hermes Agent (Reach) on a Mac Mini. The legacy plansync system is disabled and awaiting removal (MIGRATION.md Phase 4).

## What's built

- **Item store**: items with calendar / condition / after / compound triggers, soft checklists, provenance (`source_ref`, `path_id`), append-only event log with batch undo
- **Hourly eval**: deterministic (zero LLM tokens) weather pull, consecutive-day condition cache, trigger firing. Negative `prep_days` fires after the anchor date
- **Telegram surfaces**: deterministic morning briefing (6:15) and evening nudge (5 PM, silent when clear) with stable completion codes
- **MCP server**: 8 tools — `status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`, `undo`. Hermes over SSE, Claude Desktop over stdio (`docker exec`), attributed via `DISPATCH_CLIENT`
- **Path templates**: 3 built-in examples plus user-authored custom paths saved to the data volume. Validation (structural errors + warnings) gates save and instantiate; `draft_path` / `dispatch check-path` preview each item with a plain-English fire date; param defaults applied
- **Skills**: dispatch (completions by code), plan-state (domain setup from a path), path-authoring (build a template), briefing — shared by Hermes and Claude
- **plan-state library**: generic domain context schema, reconcile, YAML and Obsidian adapters

## Now

### Briefing verbosity — DONE
- **Type**: improvement
- **Notes**: Root cause was the `_section_due` function mixing overdue and today items with no bundling or cap, plus verbose `Domain — Group: Activity: Step` labels. Fixed by splitting into `_section_today` (today only) and `_section_overdue` (bundled by activity, capped at 5). Dropped domain/group prefix; switched to short dates (Aug 5). Production output went from ~25 verbose lines to ~18 compact lines. 13 new tests.

### Path template authoring — DONE
- **Type**: feature
- **Notes**: `dispatch/paths.py` validates templates (unknown trigger types, field typos, forward/unknown `after` refs, unsupported metrics, placeholder mistakes, bad dates) and previews them with plain-English fire dates. `draft_path` MCP tool and `dispatch check-path` CLI expose it; `save=true` writes custom templates to `/data/paths`. `instantiate` now refuses invalid templates and applies param defaults (lawn `lawn_sqft` was never filled). New `skills/path-authoring` skill runs the conversation. Fixed negative `prep_days` being ignored (rut hunt and garden cleanup fired on the anchor date). Claude Desktop switched to dispatch; Claude wrapper skill rewritten. 47 new tests.

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

### Plan audit and trim
- **Type**: improvement
- **What it does**: Review the three live domain definitions for activities/steps that are noise. Too many items make the briefing verbose and the completion list overwhelming. Trim or consolidate.
- **Done when**: Each domain has only activities/steps that are genuinely useful day-to-day. No "fire and forget" items cluttering the overdue list.
- **Touches**: Domain definitions in /opt/data/plansync/domains/, MCP tools (complete/defer/delete_activity)
- **Risk**: Deleting an activity the user actually wants. Confirm before removing.
- **Notes**: The built-in templates need the same audit — run `dispatch check-path <id>` with real params. Found so far: garden-fall gates fall greens "not before" the frost date itself; lawn-cool-season hardcodes 2026 dates and describes a soil-temp trigger that actually reads air temp; unused params (`zone`, `grass_type`, `stands`, `plots`).

### Back up the dispatch DB
- **Type**: bug (data safety)
- **What it does**: `dispatch.db` and custom paths live on the `plansync-new-data` Docker volume, outside `$REACH_DATA_PATH`, so the nightly backup does not cover them. Move `/data` to a bind mount under reach-data (APFS, WAL-safe) or add the volume to the backup job.
- **Done when**: A restore from last night's backup recovers the dispatch DB and custom paths.
- **Touches**: ../reach/docker-compose.yml (plansync-new volumes), backup job, MIGRATION.md
- **Risk**: Moving the volume while the container runs; copy with the container stopped.
- **Notes**:

## Next

- **Retire legacy Hermes skills** (tech debt): `skills/plansync.md`, `skills/domain-authoring.md`, and `skills/plansync-briefing.md` still load in Hermes via external_dirs but reference the disabled plansync tools. A "plan my garden" request can pick the old domain-authoring skill. Remove or disable them with MIGRATION.md Phase 4.
- **Per-entity dependencies** (feature): an `after` trigger pointed at a per-entity item resolves to the last entity's copy only, so "fertilize Bed 1 21 days after Bed 1 transplant" is not expressible. `draft_path` warns about it.
- **`after` with `event: fired`** (bug): eval ignores the event type and fires as soon as the referenced item exists. Validation rejects `fired` until eval handles it.

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
