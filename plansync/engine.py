"""Shared engine for plan-state: DB access, change logging, cascade and
trigger-date logic. Imported by both the MCP server and the sync pipeline
so the algorithm exists exactly once."""

import json
import os
import sqlite3
from datetime import date, timedelta

DEFAULT_DB_PATH = "/opt/data/plansync/plansync.db"


def db_path():
    return os.environ.get("PLANSYNC_DB", DEFAULT_DB_PATH)


def get_db():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    # Journal mode is a persistent DB property: WAL, set at init/migration time
    # (the DB lives on APFS under /opt/data -- never move it back to the
    # exFAT/VirtioFS mount, where WAL fails sporadically with SQLITE_CANTOPEN)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def row_to_dict(row):
    d = dict(row)
    for k, v in d.items():
        if k.endswith("_json") or k in ("trigger_def", "definition", "forecast_json", "old_value", "new_value"):
            if isinstance(v, str):
                try:
                    d[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass
    return d


def log_change(conn, item_type, item_id, action, old_value, new_value, source=None):
    if source is None:
        source = os.environ.get("PLANSYNC_CLIENT", "hermes")
    conn.execute(
        "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source) VALUES (?,?,?,?,?,?)",
        (item_type, item_id, action, json.dumps(old_value), json.dumps(new_value), source),
    )


def step_due_date(trigger_date_str, step_type, lead_days):
    """Due date for a step relative to its activity's trigger date:
    prep steps land lead_days before the trigger, follow_up steps after."""
    if not trigger_date_str:
        return None
    trigger_dt = date.fromisoformat(trigger_date_str)
    delta = timedelta(days=lead_days)
    return (trigger_dt - delta if step_type == "prep" else trigger_dt + delta).isoformat()


def cascade_step_dates(conn, activity_id, trigger_date_str, source=None, on_change=None):
    """Re-derive due dates for open steps from the activity's trigger date.

    on_change(step_row, old_due, new_due) fires for each step that moved.
    """
    if not trigger_date_str:
        return
    steps = conn.execute(
        "SELECT * FROM steps WHERE activity_id=? AND status NOT IN ('completed','skipped')",
        (activity_id,),
    ).fetchall()
    for s in steps:
        new_due = step_due_date(trigger_date_str, s["step_type"], s["lead_days"])
        old_due = s["due_date"]
        if new_due != old_due:
            conn.execute("UPDATE steps SET due_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_due, s["id"]))
            log_change(conn, "step", s["id"], "date_cascade", {"due_date": old_due}, {"due_date": new_due}, source=source)
            if on_change:
                on_change(s, old_due, new_due)


def derive_conditions(trigger_def):
    """Walk a trigger_def tree and return conditions-row dicts
    ({condition_type, definition}) for every clause in condition-type leaves.
    trigger_def is the source of truth; the conditions table is an evaluation
    cache the cron updates (is_met / current_value)."""
    if isinstance(trigger_def, str):
        trigger_def = json.loads(trigger_def)
    rows = []

    def walk(node):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if t == "condition":
            for clause in node.get("all", []):
                ctype = "weather_event" if "event" in clause else "temperature"
                rows.append({"condition_type": ctype, "definition": clause})
        elif t == "compound":
            for sub in node.get("conditions", []):
                walk(sub)

    walk(trigger_def)
    return rows


def defer_trigger_def(trigger_def, new_date):
    """Rewrite a trigger_def so it cannot fire before new_date.

    calendar: move the date. compound: move the calendar leg (or add one).
    condition/dependency: wrap in a compound AND with an earliest-date gate --
    the weather/dependency logic still applies, but not before new_date."""
    if isinstance(trigger_def, str):
        trigger_def = json.loads(trigger_def)
    t = trigger_def.get("type")
    if t == "calendar":
        out = dict(trigger_def)
        out["date"] = new_date
        return out
    if t == "compound":
        out = dict(trigger_def)
        subs = []
        moved = False
        for sub in trigger_def.get("conditions", []):
            if isinstance(sub, dict) and sub.get("type") == "calendar" and not moved:
                s = dict(sub)
                if "date" in s:
                    s["date"] = new_date
                else:
                    s["after"] = new_date
                subs.append(s)
                moved = True
            else:
                subs.append(sub)
        if not moved:
            subs.insert(0, {"type": "calendar", "after": new_date})
        out["conditions"] = subs
        return out
    return {
        "type": "compound",
        "operator": "AND",
        "conditions": [{"type": "calendar", "after": new_date}, trigger_def],
    }


def compute_trigger_date(trigger_def):
    if not trigger_def:
        return None
    if isinstance(trigger_def, str):
        trigger_def = json.loads(trigger_def)
    t = trigger_def.get("type")
    if t == "calendar":
        return trigger_def.get("date")
    if t == "compound":
        for sub in trigger_def.get("conditions", []):
            if sub.get("type") == "calendar":
                d = sub.get("date") or sub.get("after")
                if d:
                    return d
    return None
