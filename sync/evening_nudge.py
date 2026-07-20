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
    clear. Open = fired activities (preparing/active) plus their pending/due
    steps; watching activities haven't fired, so there is nothing to do yet."""
    items = []

    steps = conn.execute(
        """SELECT s.name AS step_name, s.due_date,
                  a.name AS activity_name, a.group_name, d.name AS domain_name
           FROM steps s
           JOIN activities a ON s.activity_id = a.id
           JOIN domains d ON a.domain_id = d.id
           WHERE s.status IN ('pending','due')
             AND s.due_date IS NOT NULL AND s.due_date <= ?
             AND a.status IN ('preparing','active')
           ORDER BY s.due_date, d.name""",
        (today,),
    ).fetchall()
    for s in steps:
        name = f'{s["activity_name"]}: {s["step_name"]}'
        line = _label(s["domain_name"], s["group_name"], name)
        when = "due today" if s["due_date"] == today else f"due {s['due_date']}"
        items.append(f"- {line} ({when})")

    activities = conn.execute(
        """SELECT a.name, a.group_name, a.trigger_date, d.name AS domain_name
           FROM activities a
           JOIN domains d ON a.domain_id = d.id
           WHERE a.status IN ('preparing','active')
             AND a.trigger_date IS NOT NULL AND a.trigger_date <= ?
           ORDER BY a.trigger_date, d.name""",
        (today,),
    ).fetchall()
    for a in activities:
        line = _label(a["domain_name"], a["group_name"], a["name"])
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
