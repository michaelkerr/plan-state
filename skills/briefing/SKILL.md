---
name: briefing
description: Re-run the morning briefing or evening nudge and send the text unchanged, or answer "what's due today". Under Hermes, fetch it with curl -sf http://dispatch:8082/api/briefing; elsewhere call the dispatch status tool.
version: 1.1.0
author: plan-state
---

# Briefing

dispatch generates the briefing and nudge deterministically from the
database.  No LLM tokens are spent gathering data, and the text is
already formatted for chat — never rewrite or summarize it.

## Morning briefing

The briefing includes:
- **Conditions** — directly under the title. Location, today's weather, and any trigger condition still being watched.
- **Overdue** — still due, date before today. Every line has a close code.
- **Due today** — due date is today. Every line has a close code.
- **The next 7 days** — still open, date inside the next 7 days, not already listed above. Every line has a close code. A `~` line has not reached its date yet; `done` still closes it and `skip` still drops it.

## Evening nudge

Lists items still due today with completion codes.  Empty output means
nothing is open: send nothing.  When there are items, deliver them and
add: "Reply `done <code>` to close, `skip <code>` to drop."

## On demand

When the user says "re-run the briefing", "send the nudge", or "what's due":

- **Hermes** (dispatch reachable on the Docker network):

  ```bash
  curl -sf http://dispatch:8082/api/briefing   # or /api/nudge
  ```

  Send stdout unchanged.

- **Any other client** (Claude, Cursor): call the dispatch `status` tool
  and show its `formatted` text unchanged.

## Scheduling

The hourly eval must run before the briefing so today's weather and
triggers are current.  Hermes cron setup is in `hermes/README.md`.
Without Hermes, run the server with `--eval-every 60` (or
`DISPATCH_EVAL_MINUTES=60`) and ask for the briefing when you want it.
