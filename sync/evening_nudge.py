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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plansync import engine  # noqa: E402

MAX_LINES = 10


def _label(domain, group, name):
    return f"{domain} — {group}: {name}" if group else f"{domain} — {name}"


def build_nudge(conn, today):
    """Message text listing open items dated today or earlier, or None if all
    clear. Steps come from the shared view: visibility is the step's own
    state, so a follow-up on a completed activity still nudges. Activities
    are the fired ones (preparing/active); watching haven't fired, so there
    is nothing to do yet."""
    items = []

    for s in engine.get_actionable_items(conn, as_of_date=today):
        name = f'{s["activity_name"]}: {s["step_name"]}'
        line = _label(s["domain_name"], s["group_name"], name)
        when = "due today" if s["due_date"] == today else f"due {s['due_date']}"
        items.append(f"- {line} ({when})")

    for a in engine.get_open_activities(conn, through_date=today,
                                        statuses=("preparing", "active")):
        line = _label(a["domain_name"], a["group_name"], a["activity_name"])
        when = "due today" if a["trigger_date"] == today else f"open since {a['trigger_date']}"
        items.append(f"- {line} ({when})")

    if not items:
        return None

    shown = items[:MAX_LINES]
    lines = [f"Still open this evening ({len(items)}):"] + shown
    if len(items) > MAX_LINES:
        lines.append(f"…and {len(items) - MAX_LINES} more — ask for the full list.")
    lines.append("Tell me what you finished and I'll check it off.")
    return "\n".join(lines)


def main():
    if not os.path.exists(engine.db_path()):
        print(f"Database not found at {engine.db_path()}", file=sys.stderr)
        sys.exit(1)
    conn = engine.get_db()
    try:
        msg = build_nudge(conn, date.today().isoformat())
    finally:
        conn.close()
    if msg:
        print(msg)


if __name__ == "__main__":
    main()
