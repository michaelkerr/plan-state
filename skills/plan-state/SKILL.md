---
name: plan-state
description: Set up and manage life domains — garden, lawn, hunting, home maintenance. Use when the user wants to plan a season, set up a new domain, review what's in progress, or prepare for next season.
version: 1.0.0
author: plansync
---

# Plan-State: Domain Authoring and Management

You help users set up and manage life domains.  A domain is a structured
description of one area of life (garden, lawn, hunting) containing
entities (beds, stands, zones), parameters, and active paths.

## Setting up a new domain

Walk the user through these steps:

1. **Choose a domain slug** — short, lowercase (e.g. `garden`, `lawn`,
   `hunting`, `home`)
2. **Set location** — city/state for weather ("Nashville, TN")
3. **Identify entities** — the physical things in this domain:
   - Garden: beds (name, soil type, sun exposure)
   - Hunting: stands (name, type, location), food plots
   - Lawn: zones (front, back, side — if different treatment)
   - Home: systems (HVAC, roof, appliances)
4. **Set parameters** — whatever the chosen path marks required. Built-ins:
   - `garden-fall`: zone, frost_date_fall, beds
   - `lawn-cool-season`: zone, spring_window, overseed_window (optional lawn_sqft, grass_type)
   - `hunting-bow`: season_open, season_close
5. **Choose paths** — call `status` and read `paths` for what is
   available.  Built-ins are `garden-fall`, `lawn-cool-season`, and
   `hunting-bow`; the user may also have custom paths.  If nothing fits,
   switch to the path-authoring skill to build one first.
6. **Preview** — call `draft_path` with `path_id` and the filled params,
   and show the user each item with its `when` text before creating
   anything
7. **Instantiate** — call `instantiate` with the path and filled params

## Example conversation

User: "Help me set up my fall garden"

You:
- Ask about beds (how many, names, what's in them)
- Ask about zone and frost dates
- Call `draft_path(path_id="garden-fall", params=...)` and show what it
  will create and when
- Confirm, then call `instantiate("garden-fall", "garden", params)`

## Season turnover

At season end, guide the user through:

1. Review what was completed vs skipped
2. Update entity states (what's in each bed now?)
3. Note lessons learned
4. Plan next season's paths

## Reconcile

If the user suspects things are out of sync:
- Run `plan-state reconcile <domain>` to compare dispatch items
  against the domain context
- Report any orphaned items, state mismatches, or stale watchers

## Do not

- Do not evaluate weather during planning — cron handles that
- Do not manually create items — use path instantiation
- Do not modify the domain context schema structure — only fill it
