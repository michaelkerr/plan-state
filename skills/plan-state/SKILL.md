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
4. **Set parameters** — zone, frost dates, season dates, acreage, etc.
5. **Choose paths** — which templates to instantiate:
   - `garden-fall` — cool-season vegetable garden
   - `lawn-cool-season` — cool-season grass annual care
   - `hunting-bow` — whitetail bow season
6. **Instantiate** — call `instantiate` with the path and filled params

## Example conversation

User: "Help me set up my fall garden"

You:
- Ask about beds (how many, names, what's in them)
- Ask about zone and frost dates
- Show what `garden-fall` will create
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
