---
name: plansync-domain-authoring
description: Plan or grow a life domain (garden, yard, lawn, hunting, health, home maintenance) in the plan-state/Gideon system. Use when the user wants to plan a season or project ("help me plan my fall garden", "set up my hunting season"), add activities to an existing domain ("add tomatoes to my garden"), or restructure domain plans. Runs the authoring conversation, then loads the result via the plansync MCP tools.
---

# Plansync domain authoring (Claude wrapper)

The canonical skill lives in the plan-state repo and is shared with Gideon
(Hermes/Telegram) so both agents author by identical rules. Do not duplicate
its content here — read it and follow it exactly:

1. **Read** `/Volumes/Elements/Projects/plan-state/skills/domain-authoring.md`
   — conversation flow, domain-scoping rules, activity-vs-step rule,
   trigger-format reference, validation rules, and complete examples.

2. **Tools** are on the `plansync` MCP server (`mcp__plansync__*`):
   `get_domains`, `get_domain_plan`, `load_domain`, `add_activities`,
   `update_activity`, `complete_activity`, `defer_activity`,
   `add_observation`, `get_upcoming`, `get_weather_current`.
   If they appear as deferred tools, load them with ToolSearch first.

Claude-specific notes:

- Writes are attributed `source='claude'` automatically (the MCP server is
  launched with `PLANSYNC_CLIENT=claude`); nothing to configure.
- There are NO single-shot create tools: a new domain goes through
  `load_domain`, growth of an existing domain through `add_activities`
  (a single new activity is a one-element array).
- Do not evaluate weather conditions during the planning conversation —
  the daily cron does that. Author trigger definitions and let it run.
- After loading, call `get_upcoming` and show the user what was created and
  what fires soonest. The domain will appear in the next morning's Telegram
  briefing automatically.
