"""Shared engine for plan-state: DB access, change logging, cascade and
trigger-date logic. Imported by both the MCP server and the sync pipeline
so the algorithm exists exactly once."""

import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone

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


def log_change(conn, item_type, item_id, action, old_value, new_value, source=None, batch_id=None):
    # batch_id groups every log entry produced by one operation (e.g. an
    # activity completion plus its cascaded step/dependency changes) into a
    # single reversible unit for undo
    if source is None:
        source = os.environ.get("PLANSYNC_CLIENT", "hermes")
    conn.execute(
        "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source, batch_id) VALUES (?,?,?,?,?,?,?)",
        (item_type, item_id, action, json.dumps(old_value), json.dumps(new_value), source, batch_id),
    )


def step_due_date(trigger_date_str, step_type, lead_days):
    """Due date for a step relative to its activity's trigger date:
    prep steps land lead_days before the trigger, follow_up steps after."""
    if not trigger_date_str:
        return None
    trigger_dt = date.fromisoformat(trigger_date_str)
    delta = timedelta(days=lead_days)
    return (trigger_dt - delta if step_type == "prep" else trigger_dt + delta).isoformat()


def cascade_step_dates(conn, activity_id, trigger_date_str, source=None, on_change=None, batch_id=None):
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
            log_change(conn, "step", s["id"], "date_cascade", {"due_date": old_due}, {"due_date": new_due},
                       source=source, batch_id=batch_id)
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


# ── State machines (Step 35) ─────────────────────────────────
# All status changes route through transition(); cascade side effects through
# react(). No caller may issue a raw UPDATE ... SET status=.

ACTIVITY_STATUSES = ("watching", "preparing", "active", "completed", "skipped")
STEP_STATUSES = ("pending", "due", "completed", "skipped")

# Sentinel: the target status comes from context["to_status"] (undo restores
# whatever state the log entry recorded -- the table can't know it statically)
CONTEXT_TARGET = object()


def _trigger_fire_target(conn, row, context):
    # Firing lands in 'preparing' when there is prep work to surface,
    # 'active' when the activity is immediately actionable
    has_prep = conn.execute(
        "SELECT COUNT(*) AS c FROM steps WHERE activity_id=? AND step_type='prep'",
        (row["id"],),
    ).fetchone()["c"]
    return "preparing" if has_prep else "active"


ACTIVITY_TRANSITIONS = {
    ("watching", "trigger_fire"): _trigger_fire_target,
    ("watching", "defer"): "watching",
    ("watching", "skip"): "skipped",
    ("preparing", "activate"): "active",
    ("preparing", "complete"): "completed",
    ("preparing", "defer"): "watching",
    ("preparing", "skip"): "skipped",
    ("active", "complete"): "completed",
    ("active", "defer"): "watching",
    ("active", "skip"): "skipped",
    ("completed", "revert"): CONTEXT_TARGET,
    ("skipped", "revert"): CONTEXT_TARGET,
}

STEP_TRANSITIONS = {
    ("pending", "complete"): "completed",
    ("pending", "parent_complete"): "completed",
    ("pending", "promote"): "due",
    ("pending", "overdue"): "due",
    ("pending", "skip"): "skipped",
    ("due", "complete"): "completed",
    ("due", "parent_complete"): "completed",
    ("due", "skip"): "skipped",
    ("completed", "uncomplete"): "pending",
    ("completed", "revert"): CONTEXT_TARGET,
    ("skipped", "revert"): CONTEXT_TARGET,
}

_ENTITIES = {
    "activity": ("activities", ACTIVITY_TRANSITIONS, ACTIVITY_STATUSES),
    "step": ("steps", STEP_TRANSITIONS, STEP_STATUSES),
}


def new_batch_id():
    return uuid.uuid4().hex[:12]


def _utcnow_iso():
    # Naive UTC ISO string, matching the format of existing completed_at rows
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def transition(conn, entity_type, entity_id, event, context=None):
    """Validate and apply one state-machine event; return side-effect events.

    context keys (all optional): batch_id, source, action (log action,
    default 'status_change'), extra (dict merged into the logged new_value),
    to_status (required for 'revert').

    Raises ValueError on unknown entity/event or a transition the table
    does not allow. A valid event that leaves the status unchanged (e.g.
    defer while watching) applies nothing and logs nothing.
    """
    context = context or {}
    if entity_type not in _ENTITIES:
        raise ValueError(f"unknown entity type '{entity_type}' (expected 'activity' or 'step')")
    table, transitions, statuses = _ENTITIES[entity_type]
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone()
    if not row:
        raise ValueError(f"{entity_type} {entity_id} not found")
    current = row["status"]

    key = (current, event)
    if key not in transitions:
        valid = sorted(e for (s, e) in transitions if s == current)
        raise ValueError(
            f"invalid transition: {entity_type} {entity_id} is '{current}', "
            f"event '{event}' not allowed (valid events from '{current}': "
            f"{', '.join(valid) if valid else 'none'})"
        )

    target = transitions[key]
    if target is CONTEXT_TARGET:
        target = context.get("to_status")
        if target not in statuses:
            raise ValueError(
                f"revert requires context['to_status'] (one of: {', '.join(statuses)}), "
                f"got {target!r}"
            )
        if target == current:
            raise ValueError(f"revert target equals current status '{current}'")
    elif callable(target):
        target = target(conn, row, context)

    if target != current:
        sets, vals = ["status=?", "updated_at=CURRENT_TIMESTAMP"], [target]
        if target == "completed":
            sets.append("completed_at=?")
            vals.append(_utcnow_iso())
        elif current == "completed":
            sets.append("completed_at=NULL")
        vals.append(entity_id)
        conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)

        new_value = {"status": target}
        new_value.update(context.get("extra") or {})
        log_change(conn, entity_type, entity_id, context.get("action", "status_change"),
                   {"status": current}, new_value,
                   source=context.get("source"), batch_id=context.get("batch_id"))

    events = []
    if entity_type == "activity" and event == "complete":
        events.append({"type": "activity_completed", "activity_id": entity_id})
    return events


def react(conn, events, batch_id, source=None):
    """Process side-effect events from transition(), producing further
    transitions as needed. Every change logs with the shared batch_id.

    activity_completed: prep steps (pending and due) complete, follow-up
    steps promote to 'due' at today + lead_days, watching dependency
    activities fire at today + offset_days with their step dates cascaded.
    """
    result = {"steps_completed": [], "follow_ups_promoted": [], "dependencies_fired": []}
    ctx = {"batch_id": batch_id, "source": source}
    queue = list(events)
    while queue:
        ev = queue.pop(0)
        if ev["type"] != "activity_completed":
            continue
        aid = ev["activity_id"]

        preps = conn.execute(
            "SELECT id, name, status FROM steps "
            "WHERE activity_id=? AND step_type='prep' AND status IN ('pending','due')",
            (aid,),
        ).fetchall()
        for s in preps:
            queue.extend(transition(conn, "step", s["id"], "parent_complete", dict(ctx)))
            result["steps_completed"].append({"id": s["id"], "name": s["name"], "was": s["status"]})

        follow_ups = conn.execute(
            "SELECT id, name, lead_days FROM steps "
            "WHERE activity_id=? AND step_type='follow_up' AND status='pending'",
            (aid,),
        ).fetchall()
        for fu in follow_ups:
            due = (date.today() + timedelta(days=fu["lead_days"])).isoformat()
            conn.execute("UPDATE steps SET due_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (due, fu["id"]))
            queue.extend(transition(conn, "step", fu["id"], "promote",
                                    dict(ctx, extra={"due_date": due})))
            result["follow_ups_promoted"].append({"id": fu["id"], "name": fu["name"], "due_date": due})

        dependents = conn.execute(
            "SELECT id, name, trigger_def FROM activities "
            "WHERE trigger_type='dependency' AND status='watching'",
        ).fetchall()
        for dep in dependents:
            tdef = json.loads(dep["trigger_def"]) if isinstance(dep["trigger_def"], str) else dep["trigger_def"]
            if not tdef or tdef.get("activity_id") != aid or tdef.get("event") != "completed":
                continue
            new_trigger = (date.today() + timedelta(days=tdef.get("offset_days", 0))).isoformat()
            conn.execute(
                "UPDATE activities SET trigger_date=?, trigger_fired=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_trigger, _utcnow_iso(), dep["id"]),
            )
            queue.extend(transition(conn, "activity", dep["id"], "trigger_fire",
                                    dict(ctx, action="trigger_fire",
                                         extra={"trigger_date": new_trigger, "fired_by": aid})))
            cascade_step_dates(conn, dep["id"], new_trigger, source=source, batch_id=batch_id)
            result["dependencies_fired"].append({"id": dep["id"], "name": dep["name"], "trigger_date": new_trigger})
    return result
