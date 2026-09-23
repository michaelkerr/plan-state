---
name: briefing
description: Re-run or re-trigger the morning briefing with curl -sf http://plansync-new:8082/api/briefing and send that text unchanged. Never curl reach-plansync. Also for what's due today and the 5 PM nudge.
version: 1.0.0
author: plansync
---

# Briefing

The dispatch system generates deterministic briefings and nudges
directly from the database.  No LLM tokens are spent on data gathering
— everything comes from `dispatch briefing` or `dispatch nudge`.

## Morning briefing (6:15 AM)

Run: `dispatch briefing`

The output includes:
- **Conditions** — directly under the title. Location, today's weather, and any trigger condition still being watched.
- **Overdue** — still due, date before today. Every line has a close code.
- **Due today** — due date is today. Every line has a close code.
- **The next 7 days** — still open, date inside the next 7 days, not already listed above. Every line has a close code. A `~` line has not reached its date yet; `done` still closes it and `skip` still drops it.

Deliver the output to Telegram as-is.  The briefing is already formatted
for chat — do not rewrite or summarize it.

## Evening nudge (5 PM)

Run: `dispatch nudge`

The output lists items still due today with completion codes.
If the output is empty, send nothing (silent when clear).

When there are items, deliver and add: "Reply `done <code>` to close, `skip <code>` to drop."

## On-demand

When the user says "re trigger the briefing", "re-run the briefing", or
"what's due":

```bash
curl -sf http://plansync-new:8082/api/briefing
```

Send that stdout unchanged. Do not summarize it. Do not call plansync
MCP tools. Do not run `morning-briefing.sh`. Do not curl
`http://reach-plansync:8082/api/briefing` — that server is the old
database.

## Cron setup

Add these to Hermes cron:

```
# Hourly eval (weather + triggers)
0 * * * *  dispatch eval --location "$DISPATCH_LOCATION"

# Morning briefing at 6:15 AM
15 6 * * *  dispatch briefing

# Evening nudge at 5 PM
0 17 * * *  dispatch nudge
```

The eval must run before the briefing so today's weather and triggers
are current.
