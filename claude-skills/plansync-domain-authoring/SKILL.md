---
name: plansync-domain-authoring
description: Plan a life domain (garden, yard, lawn, hunting, home maintenance) or build a path template in the dispatch/Reach system. Use when the user wants to plan a season ("help me plan my fall garden", "set up my hunting season"), needs a plan no existing template covers ("make a template for spring garlic"), or wants to close, defer, or list items. Runs the conversation, then calls the dispatch MCP tools.
---

# Dispatch domain and path authoring (Claude wrapper)

The canonical skills live in the plan-state repo and are shared with Reach
(Hermes/Telegram) so both agents follow identical rules. Do not duplicate
their content here — read the one that fits and follow it exactly:

- **Set up a domain from a path** (existing template):
  `/Users/michaelkerr/Projects/plan-state/skills/plan-state/SKILL.md`
- **Build or edit a path template** (nothing existing fits):
  `/Users/michaelkerr/Projects/plan-state/skills/path-authoring/SKILL.md`
- **Close, skip, defer, or list items by code** (G1, L2):
  `/Users/michaelkerr/Projects/plan-state/skills/dispatch/SKILL.md`

**Tools** are on the `dispatch` MCP server (`mcp__dispatch__*`):
`status`, `done`, `skip`, `defer`, `note`, `instantiate`, `draft_path`,
`undo`. If they appear as deferred tools, load them with ToolSearch first.

Claude-specific notes:

- Writes are attributed `source='claude'` automatically (the MCP server is
  launched with `DISPATCH_CLIENT=claude`); nothing to configure.
- The old plansync tools (`load_domain`, `add_activities`,
  `complete_activity`, ...) are retired. Do not look for them.
- Do not evaluate weather conditions while planning — the hourly job does
  that.
- After instantiating, call `status` and show what was created. New items
  appear in the next morning's Telegram briefing automatically.
