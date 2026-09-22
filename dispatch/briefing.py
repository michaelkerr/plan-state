"""dispatch.briefing — morning briefing generator.

Deterministic, zero LLM tokens.  Reads the DB at call time.  No cached
markdown, no daily JSON, no dossiers.
"""

from datetime import datetime, timedelta

from dispatch.store import connect, row_to_dict
from dispatch.resolve import format_code_list


def build_briefing(today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.strptime(today, "%Y-%m-%d")
                + timedelta(days=1)).strftime("%Y-%m-%d")
    week_end = (datetime.strptime(today, "%Y-%m-%d")
                + timedelta(days=7)).strftime("%Y-%m-%d")

    with connect() as conn:
        sections = []

        # 1. Due today
        due_today = conn.execute(
            "SELECT * FROM items WHERE status='due' AND due_date <= ? "
            'ORDER BY domain, "group", sort_order',
            (today,),
        ).fetchall()
        due_today = [row_to_dict(r) for r in due_today]

        if due_today:
            sections.append(_section("Due today", due_today))

        # 2. Overdue (due before today, still status=due)
        overdue = conn.execute(
            "SELECT * FROM items WHERE status='due' AND due_date < ? "
            'ORDER BY due_date, domain, "group"',
            (today,),
        ).fetchall()
        overdue = [row_to_dict(r) for r in overdue]

        if overdue:
            sections.append(_section("Overdue", overdue, max_items=5))

        # 3. Fired in last 24 hours
        yesterday = (datetime.strptime(today, "%Y-%m-%d")
                     - timedelta(days=1)).strftime("%Y-%m-%d")
        fired = conn.execute(
            "SELECT * FROM event_log WHERE event_type='item_fired' "
            "AND timestamp >= ? ORDER BY timestamp",
            (yesterday,),
        ).fetchall()
        if fired:
            fired_items = []
            for ev in fired:
                ev = row_to_dict(ev)
                item = conn.execute(
                    "SELECT * FROM items WHERE id=?",
                    (ev.get("item_id"),),
                ).fetchone()
                if item:
                    fired_items.append(row_to_dict(item))
            if fired_items:
                sections.append(_section("Newly triggered", fired_items))

        # 4. Coming this week
        upcoming = conn.execute(
            "SELECT * FROM items WHERE status IN ('watching','due') "
            "AND due_date > ? AND due_date <= ? "
            'ORDER BY due_date, domain, "group"',
            (today, week_end),
        ).fetchall()
        upcoming = [row_to_dict(r) for r in upcoming]

        if upcoming:
            sections.append(_section("This week", upcoming, max_items=8))

        # 5. Weather summary
        weather = conn.execute(
            "SELECT * FROM weather_log WHERE weather_date=? "
            "ORDER BY location",
            (today,),
        ).fetchall()
        if weather:
            wx_lines = []
            for w in weather:
                w = row_to_dict(w)
                high = w.get("temp_high")
                low = w.get("temp_low")
                conds = w.get("conditions", [])
                loc = w.get("location", "?")
                wx_lines.append(
                    f"  {loc}: {low or '?'}°–{high or '?'}°F"
                    + (f" ({', '.join(conds)})" if conds else "")
                )
            sections.append("**Weather**\n" + "\n".join(wx_lines))

        # 6. Stable codes for quick completion
        all_open = conn.execute(
            'SELECT * FROM items WHERE status IN (\'watching\',\'due\') '
            'ORDER BY domain, "group", sort_order, due_date',
        ).fetchall()
        all_open = [row_to_dict(r) for r in all_open]
        if all_open:
            sections.append("**Quick close**" + format_code_list(all_open))

        if not sections:
            return ""

        header = f"Morning briefing — {_format_date(today)}"
        return f"**{header}**\n\n" + "\n\n".join(sections)


def _section(title, items, max_items=None):
    lines = [f"**{title}**"]
    shown = items[:max_items] if max_items else items
    for item in shown:
        name = item["name"]
        group = item.get("group")
        if group:
            name = f"{group}: {name}"
        due = f" (due {_short_date(item['due_date'])})" if item.get("due_date") else ""
        lines.append(f"  • {name}{due}")
    if max_items and len(items) > max_items:
        lines.append(f"  …and {len(items) - max_items} more")
    return "\n".join(lines)


def _format_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%A, %b %-d")


def _short_date(date_str):
    if not date_str:
        return ""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %-d")
