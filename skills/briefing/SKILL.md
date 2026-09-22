---
name: briefing
description: Generate a morning briefing or evening nudge from dispatch. Use at scheduled times (6:15 AM briefing, 5 PM nudge) or when the user asks what's happening today.
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
- **Due today** — items with today's due date
- **Overdue** — items past their due date
- **Newly triggered** — items that fired in the last 24 hours
- **This week** — upcoming items within 7 days
- **Weather** — today's conditions by location
- **Quick close codes** — stable codes (G1, L2) for fast completion

Deliver the output to Telegram as-is.  The briefing is already formatted
for chat — do not rewrite or summarize it.

## Evening nudge (5 PM)

Run: `dispatch nudge`

The output lists items still due today with completion codes.
If the output is empty, send nothing (silent when clear).

When there are items, deliver and add: "Reply `done <code>` to close."

## On-demand

When the user asks "what's due?" or "what's happening today?", run
`dispatch briefing` and deliver the result.

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
