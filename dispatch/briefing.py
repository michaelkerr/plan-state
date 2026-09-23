"""dispatch.briefing — morning briefing generator.

Deterministic, zero LLM tokens.  Reads the DB at call time.  No cached
markdown, no daily JSON, no dossiers.
"""

from datetime import datetime, timedelta

from dispatch.store import _after_fire_date, connect, get_items, row_to_dict
from dispatch.resolve import _assign_codes


def build_briefing(today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    week_end = (datetime.strptime(today, "%Y-%m-%d")
                + timedelta(days=7)).strftime("%Y-%m-%d")

    with connect() as conn:
        sections = []

        conditions = _conditions_section(conn, today)
        if conditions:
            sections.append(conditions)

        all_items = get_items(conn)
        codes = {item["id"]: code for item, code in _assign_codes(all_items)}

        overdue = [item for item in all_items
                   if item["status"] == "due"
                   and item.get("due_date") and item["due_date"] < today]
        due_today = [item for item in all_items
                     if item["status"] == "due" and item.get("due_date") == today]
        by_id = {item["id"]: item for item in all_items}
        shown = {item["id"] for item in overdue + due_today}
        next_days = [item for item in all_items
                     if item["id"] not in shown
                     and item["status"] in ("watching", "due")
                     and _event_date(item, by_id, today)
                     and today < _event_date(item, by_id, today) <= week_end]

        def _sort_key(item):
            return (_event_date(item, by_id, today) or "",
                    item["domain"], item.get("group") or "")

        if overdue:
            sections.append(_coded_section(
                "Overdue", sorted(overdue, key=_sort_key), codes, by_id, today))
        if due_today:
            sections.append(_coded_section(
                "Due today", sorted(due_today, key=_sort_key), codes, by_id, today))
        if next_days:
            sections.append(_coded_section(
                "The next 7 days", sorted(next_days, key=_sort_key), codes, by_id, today))

        if not sections:
            return ""

        if overdue or due_today or next_days:
            sections.append("Reply `done <code>` to close, `skip <code>` to drop.")

        header = f"Morning briefing — {_format_date(today)}"
        return f"**{header}**\n\n" + "\n\n".join(sections)


def _conditions_section(conn, today):
    """Location, today's weather, and trigger conditions still being watched."""
    lines = ["**Conditions**"]

    weather_rows = conn.execute(
        "SELECT * FROM weather_log WHERE weather_date=? ORDER BY location",
        (today,),
    ).fetchall()
    for row in weather_rows:
        w = row_to_dict(row)
        lines.append(f"  Location: {w.get('location') or '?'}")
        weather = _weather_line(w)
        if weather:
            lines.append(f"  Weather: {weather}")

    rows = conn.execute(
        """SELECT cc.metric, cc.operator, cc.value, cc.sustained_days,
                  cc.current_value, cc.is_met
           FROM conditions_cache cc
           JOIN items i ON i.id = cc.item_id
           WHERE i.status = 'watching'
           ORDER BY cc.metric, cc.operator, cc.value, cc.sustained_days"""
    ).fetchall()
    seen = set()
    for row in rows:
        row = dict(row)
        key = (row["metric"], row["operator"], row["value"], row["sustained_days"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"  {_condition_line(row)}")

    if len(lines) == 1:
        return None
    return "\n".join(lines)


def _weather_line(w):
    parts = []
    if w.get("temp_current") is not None:
        parts.append(f"{_temp(w['temp_current'])} now")
    low = w.get("temp_low")
    high = w.get("temp_high")
    if low is not None or high is not None:
        parts.append(f"{_temp(low)}–{_temp(high)}")
    sky = w.get("conditions") or []
    if isinstance(sky, str):
        sky = [sky]
    sky = ", ".join(bit for bit in sky if bit)
    text = ", ".join(parts)
    if sky:
        text = f"{text}, {sky}" if text else sky
    return text


def _condition_line(row):
    days = row["sustained_days"] or 1
    span = f" for {days} days" if days > 1 else ""
    state = "met" if row["is_met"] else "not met"
    now = ""
    if row["current_value"] is not None:
        now = f", now {_temp(row['current_value'])}"
    return (
        f"{row['metric']} {row['operator']} {row['value']:g}°{span}: "
        f"{state}{now}"
    )


def _coded_section(title, items, codes, by_id, today):
    lines = [f"**{title}**"]
    for item in items:
        marker = "!" if item["status"] == "due" else "~"
        name = item["name"]
        group = item.get("group")
        if group:
            name = f"{group}: {name}"
        when = _event_date(item, by_id, today)
        due = f" (due {_short_date(when)})" if when else ""
        lines.append(f"  {marker} [{codes[item['id']]}] {name}{due}")
    return "\n".join(lines)


def _event_date(item, by_id, today):
    """Date to show and sort on. Fired items use due_date. A watching
    calendar item uses its trigger date. A watching follow-up uses the
    parent's completion date plus its offset.
    """
    if item.get("due_date"):
        return item["due_date"]
    trigger = item.get("trigger_def") or {}
    if trigger.get("type") == "calendar":
        return trigger.get("date")
    if item.get("status") == "watching" and trigger.get("type") == "after":
        parent = by_id.get(trigger.get("item_ref"))
        if parent and parent.get("status") == "done":
            return _after_fire_date(None, trigger, today, parent=parent)
    return None


def _format_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%A, %b %-d")


def _short_date(date_str):
    if not date_str:
        return ""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %-d")


def _temp(value):
    if value is None:
        return "?"
    rounded = round(float(value), 1)
    if rounded == int(rounded):
        return f"{int(rounded)}°"
    return f"{rounded}°"
