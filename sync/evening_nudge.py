#!/usr/bin/env python3
"""
Evening nudge: list plan items still open as of today. Deterministic, zero LLM
tokens. Replaces Todoist's due-time reminder: anything due today or overdue
that hasn't been completed (via chat -> complete_activity) gets one evening
mention. Prints NOTHING when nothing is open -- no output, no Telegram message.
"""

import os
import sys
from datetime import date

from plansync import engine

MAX_LINES = 10


def _short_date(iso_date):
    return date.fromisoformat(iso_date).strftime("%b %-d")


def build_nudge(conn, today):
    """Message text listing open items dated today or earlier, or None if all
    clear. Steps come from the shared view: visibility is the step's own
    state, so a follow-up on a completed activity still nudges. Activities
    are the fired ones (preparing/active); watching haven't fired, so there
    is nothing to do yet.

    Steps are bundled by activity to reduce line count."""
    step_rows = engine.get_actionable_items(conn, as_of_date=today)
    act_rows = engine.get_open_activities(conn, through_date=today,
                                          statuses=("preparing", "active"))

    by_activity = {}
    for s in step_rows:
        aid = s["activity_id"]
        if aid not in by_activity:
            by_activity[aid] = {
                "activity_name": s["activity_name"],
                "steps": [],
                "earliest": s["due_date"],
            }
        by_activity[aid]["steps"].append(s["step_name"])
        if s["due_date"] < by_activity[aid]["earliest"]:
            by_activity[aid]["earliest"] = s["due_date"]

    lines = []
    for info in by_activity.values():
        dt = "due today" if info["earliest"] == today else f"due {_short_date(info['earliest'])}"
        if len(info["steps"]) == 1:
            lines.append(f"- {info['activity_name']}: {info['steps'][0]} ({dt})")
        else:
            lines.append(
                f"- {info['activity_name']}: {len(info['steps'])} steps ({dt})"
            )

    step_activity_ids = {s["activity_id"] for s in step_rows}
    for a in act_rows:
        if a["activity_id"] in step_activity_ids:
            continue
        dt = "due today" if a["trigger_date"] == today else f"since {_short_date(a['trigger_date'])}"
        lines.append(f"- {a['activity_name']} ({dt})")

    if not lines:
        return None

    total_items = len(step_rows) + sum(
        1 for a in act_rows if a["activity_id"] not in step_activity_ids
    )
    shown = lines[:MAX_LINES]
    result = [f"Still open this evening ({total_items}):"] + shown
    if len(lines) > MAX_LINES:
        result.append(f"…and {len(lines) - MAX_LINES} more — ask for the full list.")
    result.append("Tell me what you finished and I'll check it off.")
    return "\n".join(result)


def main():
    if not os.path.exists(engine.db_path()):
        print(f"Database not found at {engine.db_path()}", file=sys.stderr)
        sys.exit(1)
    with engine.connect() as conn:
        msg = build_nudge(conn, date.today().isoformat())
    if msg:
        print(msg)


if __name__ == "__main__":
    main()
