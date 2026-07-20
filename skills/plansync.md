# Plan Sync Skill

You have access to the plan-sync MCP tools for managing domain plans.
These tools read/write a SQLite database that tracks activities,
conditions, and prep steps. Telegram chat is the sole task surface:
the morning briefing and evening nudge report what is due, and the
user reports completions conversationally.

## Available Tools (via plansync MCP server)

- get_domains() -- list all domains
- get_domain_plan(domain_id) -- full plan state for a domain
- create_activity(...) -- create activity with steps and triggers
- update_activity(...) -- modify an existing activity
- complete_activity(...) -- mark done, cascade follow-ups
- defer_activity(...) -- push dates, re-cascade
- create_domain(...) -- new domain (single domain, no activities)
- load_domain(definition) -- bulk-load a complete domain with all activities, steps, conditions in one call
- add_activities(domain_id, activities) -- add activities to an existing domain; activity_ref can reference activities already in the domain
- add_observation(...) -- record field observation
- get_upcoming(days_ahead) -- cross-domain upcoming view
- get_weather_current(location) -- latest weather + forecast

## Workflow

1. Always call get_domain_plan() before modifying a domain.
   Read current state first.
2. When creating activities, include all prep and follow-up steps
   with realistic lead_days.
   Set group_name to bundle related activities within a domain
   (crop, bed, species -- e.g. all three tomato activities get
   group_name "Tomatoes"). It is display-only; trigger logic
   comes from dependencies, not groups.
3. For condition-based triggers, be specific about metrics,
   thresholds, and sustained_days requirements.
4. After modifications, call get_upcoming() to show the user
   what changed and what's coming up.
5. When the user reports a field observation, use add_observation()
   and then decide whether any activities need updating.

## Trigger Types

### Calendar
Fixed date. Use when the activity has a known target date.
```json
{"type": "calendar", "date": "2026-08-25"}
```

### Condition
Weather/soil condition threshold. The cron job evaluates these daily.
```json
{"type": "condition", "all": [
  {"metric": "soil_temp", "operator": ">=", "value": 55, "sustained_days": 3}
]}
```

### Dependency
Fires when another activity completes, with optional offset.
```json
{"type": "dependency", "activity_id": "abc123", "event": "completed", "offset_days": 7}
```

### Compound
Combine calendar and condition triggers.
```json
{"type": "compound", "operator": "AND", "conditions": [
  {"type": "calendar", "after": "2026-08-15"},
  {"type": "condition", "metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 3}
]}
```

## Important

- The cron sync job handles condition evaluation. Do NOT try to
  evaluate weather conditions during a planning conversation.
- When the user says they finished something ("done with the
  fungicide"), find the matching activity or step and call
  complete_activity -- this is the ONLY completion path.
- Dates cascade automatically when you defer or update trigger_dates.
- If the user asks "what's coming up," call get_upcoming() rather
  than trying to reconstruct the schedule from memory.
- Use update_activity to modify existing activities. Do not delete
  and recreate.
- To grow an existing domain, use add_activities -- do not create a
  new domain for activities that belong to an existing one.
- When deferring, always include a reason so the activity log
  captures why the date moved.
