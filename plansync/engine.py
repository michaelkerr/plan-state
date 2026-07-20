"""Shared engine for plan-state: DB access, change logging, cascade and
trigger-date logic. Imported by both the MCP server and the sync pipeline
so the algorithm exists exactly once."""

import json
import os
import sqlite3
from datetime import date, timedelta

DEFAULT_DB_PATH = "/opt/plansync/plansync.db"


def db_path():
    return os.environ.get("PLANSYNC_DB", DEFAULT_DB_PATH)


def get_db():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    # No WAL here: unsupported on the exFAT/VirtioFS mount (see init-db.py)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def row_to_dict(row):
    d = dict(row)
    for k, v in d.items():
        if k.endswith("_json") or k in ("trigger_def", "recurrence", "condition", "definition", "forecast_json", "old_value", "new_value"):
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
