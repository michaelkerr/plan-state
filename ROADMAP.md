# Roadmap

## Product summary

dispatch is a condition-aware task system for personal life domains — lawn, garden, hunting, home. Reusable YAML path templates are instantiated into items with triggers; an hourly deterministic job evaluates weather and fires them; briefings carry one-code completions ("done G1"). A first-time install is `docker compose up` or `pip install -e .`.

## What's built

- **Item store**: items with calendar / condition / after / compound triggers, soft checklists, provenance (`source_ref`, `path_id`), append-only event log with batch undo
- **Hourly eval**: deterministic weather pull; condition streaks recomputed from `weather_log` (calendar days, not hourly runs). Negative `prep_days` fires after the anchor date. Built-in scheduler (`DISPATCH_EVAL_MINUTES`) for installs without Hermes cron
- **First-time install**: `docker compose up` or `pip install -e .`; doctor names the next missing piece; README covers Claude/Cursor/Hermes
- **Telegram surfaces**: deterministic morning briefing (6:15) and evening nudge (5 PM, silent when clear) with stable completion codes
- **MCP server**: 8 tools — `status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`, `undo`. SSE or stdio; writes attributed via `DISPATCH_CLIENT`
- **Path templates**: 3 built-in examples (date params, not hardcoded seasons) plus user-authored custom paths saved to the data volume. Validation (structural errors + warnings) gates save and instantiate; `draft_path` / `dispatch check-path` preview each item with a plain-English fire date; param defaults applied
- **CI**: GitHub Action runs pytest on 3.10 and 3.12
- **Skills**: dispatch (completions by code), plan-state (domain setup from a path), path-authoring (build a template), briefing — shared by Hermes and Claude
- **plan-state library**: generic domain context schema, reconcile, YAML and Obsidian adapters

## Now

### Briefing verbosity — DONE
- **Type**: improvement
- **Notes**: Root cause was the `_section_due` function mixing overdue and today items with no bundling or cap, plus verbose `Domain — Group: Activity: Step` labels. Fixed by splitting into `_section_today` (today only) and `_section_overdue` (bundled by activity, capped at 5). Dropped domain/group prefix; switched to short dates (Aug 5). Production output went from ~25 verbose lines to ~18 compact lines. 13 new tests.

### Path template authoring — DONE
- **Type**: feature
- **Notes**: `dispatch/paths.py` validates templates (unknown trigger types, field typos, forward/unknown `after` refs, unsupported metrics, placeholder mistakes, bad dates) and previews them with plain-English fire dates. `draft_path` MCP tool and `dispatch check-path` CLI expose it; `save=true` writes custom templates to `/data/paths`. `instantiate` now refuses invalid templates and applies param defaults (lawn `lawn_sqft` was never filled). New `skills/path-authoring` skill runs the conversation. Fixed negative `prep_days` being ignored (rut hunt and garden cleanup fired on the anchor date). Claude Desktop switched to dispatch; Claude wrapper skill rewritten. 47 new tests.

### First-time GitHub install — DONE
- **Type**: improvement
- **Notes**: README is a clone → `.env` → `docker compose up` (or pip) → connect Claude/Cursor/Hermes path. Doctor names the next missing piece. Built-in eval loop for installs without Hermes cron. Legacy plansync tree deleted. Condition streaks now count calendar days from weather_log. Live `plansync-new` gets a `dispatch` network alias so shipped skills/cron use one hostname.

### Easier completions
- **Type**: improvement
- **What it does**: Completing an activity requires too much typing and one or more LLM round-trips (user says "done with X" → agent parses → agent calls complete_activity). Reduce the friction — faster identification of the activity, fewer steps to confirm.
- **Done when**: The user can close a common task in under 10 seconds from Telegram with at most one confirmation.
- **Touches**: skills/dispatch/SKILL.md, dispatch/resolve.py, dispatch/nudge.py
- **Risk**: Shorthand matching could misidentify activities. Need to confirm before acting.
- **Notes**:

### Architecture visualization — DONE
- **Type**: infrastructure
- **Notes**: Published as interactive artifact. Component map with click-for-details, daily cron timeline, four expandable data-flow walkthroughs (sync, completion, authoring, undo). Dark-mode aware. https://claude.ai/code/artifact/9908c269-1654-4c07-a218-a8bd0e4e1974

### Plan audit and trim
- **Type**: improvement
- **What it does**: Review the three live domain definitions for activities/steps that are noise. Too many items make the briefing verbose and the completion list overwhelming. Trim or consolidate.
- **Done when**: Each domain has only activities/steps that are genuinely useful day-to-day. No "fire and forget" items cluttering the overdue list.
- **Touches**: live dispatch items (status / skip / done), built-in path templates if a trim belongs in the example
- **Risk**: Deleting an activity the user actually wants. Confirm before removing.
- **Notes**: Live garden items still want a trim. Built-in templates (v1.1.0) take this season's dates as params — no 2026 literals, unused `zone`/`grass_type`/`stands`/`plots` removed or wired in, lawn copy matches air-temp eval, garden greens/roots are calendar+condition.

### Back up the dispatch DB
- **Type**: bug (data safety)
- **What it does**: On Hermes installs, `dispatch.db` and custom paths often live on a named Docker volume outside the Hermes data dir, so the nightly backup misses them. Bind-mount `/data` under the backed-up data path (APFS, WAL-safe) or add the volume to the backup job.
- **Done when**: A restore from last night's backup recovers the dispatch DB and custom paths.
- **Touches**: Hermes compose volumes, backup job
- **Risk**: Moving the volume while the container runs; copy with the container stopped.
- **Notes**:

## Next

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
- **v2 federated signal/boundary agents**: Shelved design. A more elaborate agent architecture dropped in favor of plan-management-first. Revisit only if a full season of operation surfaces a concrete limitation.
- **Recurrence**: Explicitly unsupported (validation rejects it). Annual plans are re-authored each season via a planning conversation. Revisit only if the re-authoring workflow proves too heavy.
