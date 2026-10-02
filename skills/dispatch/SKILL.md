---
name: dispatch
description: Close, skip, or list dispatch items by nudge codes such as G1, H3, or L1. Use when the user says done, skip, closed, completed, or asks what is open or due. Call the dispatch MCP tools. Do not write a daily log instead of calling the tool.
version: 1.1.0
author: plan-state
---

# Dispatch

Nudge and briefing codes (G1, H3, L1) are dispatch items. Closing one
changes the dispatch database. A daily note is not a completion.

## Tools

Call these exact tools. One call per code.

- `mcp__dispatch__done` — query is the code (`G1`) or a name. Marks it done.
- `mcp__dispatch__skip` — query is the code. Leaves the list without marking it done. If that tool is not listed, say the item was not skipped. Do not write it to a note instead. If that tool is not listed, say the item was not skipped. Do not write it to a note instead.
- `mcp__dispatch__status` — open items with the same codes as the nudge.
- `mcp__dispatch__defer` — query plus new_date (`YYYY-MM-DD`).
- `mcp__dispatch__note` — query plus text.
- `mcp__dispatch__undo` — revert the last change.

## When the user replies to a nudge

"done G1, H1, skip H3" means three tool calls: done, done, skip.
Pass each code as `query`. Do not look up an id first.
If a call returns several matches, ask which one. Do not guess.

## When the user asks what is open

Call `mcp__dispatch__status` and show its `formatted` text.

## Do not

- Do not write these codes into a daily log instead of calling the tool
- Do not evaluate weather — the hourly job does that

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
