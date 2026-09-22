---
name: dispatch
description: Complete tasks, check status, and manage items in the dispatch execution engine. Use when the user reports something done, asks what's due, or wants to defer a task.
version: 1.0.0
author: plansync
---

# Dispatch

You have access to the dispatch MCP tools for managing condition-aware
tasks.  These tools operate on **items** — actionable units that are
`watching` (waiting for a trigger), `due` (triggered and actionable),
`done`, or `skipped`.

## Available tools

- **status** — Show all open items with stable codes (e.g. G3, L1)
- **done** — Complete an item by code, name, or ID
- **defer** — Defer an item to a new date
- **note** — Add a note or observation to an item
- **instantiate** — Create items from a path template
- **undo** — Revert the most recent operation

## Completion workflow

When the user says they finished something:

1. Call `done` with their words (e.g. `done("tomatoes")` or `done("G3")`)
2. If the match is exact, it completes immediately
3. If ambiguous, the tool returns candidates — ask the user to pick
4. Include any notes the user mentioned: `done("G3", notes="done early, frost coming")`

Never call `status` just to look up an ID before `done` — the resolver
handles name/code matching directly.

## Briefing codes

The morning briefing and evening nudge show items with stable codes like:

```
**Garden**
  ! [G1] Transplant brassicas to Bed 1 (due Sep 25)
  ~ [G2] Direct sow greens in Bed 1
**Lawn**
  ! [L1] Apply spring pre-emergent (due Sep 22)
```

`!` = due now, `~` = watching.  The user can say "done G1" to close an
item.  Always include these codes when showing items.

## Do not

- Do not call `status` before every `done` — the resolver matches
  directly
- Do not evaluate weather conditions — the hourly cron handles that
- Do not manually set item statuses — use `done`, `defer`, or `undo`
