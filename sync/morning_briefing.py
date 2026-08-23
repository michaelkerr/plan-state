#!/usr/bin/env python3
"""Deterministic morning briefing: zero LLM tokens, same pattern as the
evening nudge. Replaces the LLM-mediated briefing_context.py -> plansync-briefing
skill pipeline that suffered from stale-data hallucination and phantom completions.

Sections:
1. What happened since yesterday (trigger fires, completions)
2. Today's priorities (due today or overdue)
3. This week (next 7 days)
4. Conditions watch (active condition-triggered activities)
5. Weather (today's forecast)

Prints a heartbeat even when all clear — the daily message confirms the system ran.
"""

import json
import os
import sys
from datetime import date, timedelta

from plansync import engine

TODAY = date.today().isoformat()
WEEK_CUTOFF = (date.today() + timedelta(days=7)).isoformat()
WEEKDAY = date.today().strftime("%A")
DATE_DISPLAY = date.today().strftime("%B %-d")
MAX_WEEK_PER_DOMAIN = 4


def _label(domain, group, name):
    return f"{domain} — {group}: {name}" if group else f"{domain} — {name}"


def _section_fires(conn):
    """Trigger fires and completions in the last 24 hours."""
    fires = conn.execute(
        """SELECT a.name as activity, a.group_name, d.name as domain,
                  json_extract(l.new_value, '$.reason') as reason
           FROM activity_log l
           JOIN activities a ON a.id = l.item_id
           JOIN domains d ON a.domain_id = d.id
           WHERE l.action = 'trigger_fire'
             AND l.timestamp >= datetime('now', '-1 day')
           ORDER BY l.timestamp""",
    ).fetchall()

    completions = conn.execute(
        """SELECT a.name as activity, a.group_name, d.name as domain
           FROM activity_log l
           JOIN activities a ON a.id = l.item_id
           JOIN domains d ON a.domain_id = d.id
           WHERE l.action = 'status_change'
             AND l.item_type = 'activity'
             AND json_extract(l.new_value, '$.status') = 'completed'
             AND l.timestamp >= datetime('now', '-1 day')
           ORDER BY l.timestamp""",
    ).fetchall()

    lines = []
    for f in fires:
        label = _label(f["domain"], f["group_name"], f["activity"])
        reason = f["reason"] or "triggered"
        lines.append(f"- {label} — {reason}")
    for c in completions:
        label = _label(c["domain"], c["group_name"], c["activity"])
        lines.append(f"- {label} — completed")

    if not lines:
        return None
    return "**What happened since yesterday**\n" + "\n".join(lines)


def _section_due(conn):
    """Steps due today or overdue."""
    items = engine.get_actionable_items(conn, as_of_date=TODAY)
    if not items:
        return None

    lines = []
    for s in items:
        name = f'{s["activity_name"]}: {s["step_name"]}'
        label = _label(s["domain_name"], s["group_name"], name)
        if s["due_date"] == TODAY:
            lines.append(f"- {label} (due today)")
        else:
            lines.append(f"- {label} (overdue, due {s['due_date']})")
    return "**Today**\n" + "\n".join(lines)


def _section_week(conn):
    """Steps and activities coming up in the next 7 days."""
    week_steps = [
        s for s in engine.get_actionable_items(conn, as_of_date=WEEK_CUTOFF)
        if s["due_date"] > TODAY
    ]
    week_acts = [
        a for a in engine.get_open_activities(conn, through_date=WEEK_CUTOFF)
        if (a["trigger_date"] or "") > TODAY
    ]

    if not week_steps and not week_acts:
        return None

    by_domain = {}
    for s in week_steps:
        d = s["domain_name"]
        name = f'{s["activity_name"]}: {s["step_name"]}'
        label = _label(d, s["group_name"], name)
        by_domain.setdefault(d, []).append(f"- {label} ({s['due_date']})")

    for a in week_acts:
        d = a["domain_name"]
        label = _label(d, a["group_name"], a["activity_name"])
        by_domain.setdefault(d, []).append(f"- {label} ({a['trigger_date']})")

    lines = []
    for domain in sorted(by_domain):
        items = by_domain[domain]
        if len(items) <= MAX_WEEK_PER_DOMAIN:
            lines.extend(items)
        else:
            lines.extend(items[:MAX_WEEK_PER_DOMAIN - 1])
            remaining = len(items) - (MAX_WEEK_PER_DOMAIN - 1)
            lines.append(f"- {domain}: {remaining} more this week — ask for the list.")

    return "**This week**\n" + "\n".join(lines)


def _section_conditions(conn):
    """Active condition-triggered watches with current values."""
    cutoff = (date.today() + timedelta(days=45)).isoformat()
    rows = conn.execute(
        """SELECT a.name as activity, a.group_name, d.name as domain,
                  a.trigger_def, a.status as activity_status, a.trigger_date
           FROM activities a
           JOIN domains d ON a.domain_id = d.id
           WHERE a.status IN ('watching', 'active')
             AND a.trigger_type IN ('condition', 'compound')
             AND (a.trigger_date IS NULL OR a.trigger_date <= ?)""",
        (cutoff,),
    ).fetchall()
    if not rows:
        return None

    lines = []
    for r in rows:
        try:
            tdef = json.loads(r["trigger_def"]) if isinstance(r["trigger_def"], str) else r["trigger_def"]
        except (json.JSONDecodeError, TypeError):
            continue

        clauses = _extract_condition_clauses(tdef)
        if not clauses:
            continue

        label = _label(r["domain"], r["group_name"], r["activity"])
        status_tag = "active" if r["activity_status"] == "active" else "watching"
        threshold_parts = []
        for c in clauses:
            metric = c.get("metric", "?").replace("_", " ")
            op = c.get("operator", "?")
            val = c.get("value", "?")
            days = c.get("sustained_days")
            part = f"{metric} {op} {val}F"
            if days and days > 1:
                part += f" for {days}d"
            threshold_parts.append(part)
        threshold = ", ".join(threshold_parts)
        lines.append(f"- {label} [{status_tag}] — {threshold}")

    if not lines:
        return None
    return "**Conditions watch**\n" + "\n".join(lines)


def _extract_condition_clauses(tdef):
    """Pull condition clauses from a trigger_def (handles compound nesting)."""
    if tdef.get("type") == "condition":
        return tdef.get("all", [])
    if tdef.get("type") == "compound":
        clauses = []
        for sub in tdef.get("conditions", []):
            clauses.extend(_extract_condition_clauses(sub))
        return clauses
    return []


def _section_weather(conn):
    """Today's weather in one line per location."""
    rows = conn.execute(
        """SELECT location, temp_high, temp_low, conditions, precipitation
           FROM weather_log
           WHERE weather_date = date('now', 'localtime')
           ORDER BY location""",
    ).fetchall()
    if not rows:
        return None

    lines = []
    for w in rows:
        hi = round(w["temp_high"]) if w["temp_high"] is not None else "?"
        lo = round(w["temp_low"]) if w["temp_low"] is not None else "?"
        cond = w["conditions"] or "?"
        precip = w["precipitation"] or 0
        line = f"- {w['location']}: {hi}/{lo}F, {cond}"
        if precip > 0:
            line += f", {precip:.1f}\" precip"
        lines.append(line)
    return "**Weather**\n" + "\n".join(lines)


def build_briefing(conn):
    header = f"Good morning. {WEEKDAY}, {DATE_DISPLAY}."

    sections = [
        _section_fires(conn),
        _section_due(conn),
        _section_week(conn),
        _section_conditions(conn),
        _section_weather(conn),
    ]
    active = [s for s in sections if s is not None]

    if not active:
        weather = _section_weather(conn)
        if weather:
            return f"{header}\n\nAll quiet — nothing due today, nothing new this week.\n\n{weather}"
        return f"{header}\n\nAll quiet — sync ran clean, nothing due today, nothing new this week."

    return header + "\n\n" + "\n\n".join(active)


def main():
    if not os.path.exists(engine.db_path()):
        print(f"Database not found at {engine.db_path()}", file=sys.stderr)
        sys.exit(1)
    with engine.connect() as conn:
        print(build_briefing(conn))


if __name__ == "__main__":
    main()
