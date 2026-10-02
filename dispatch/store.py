"""dispatch.store — SQLite storage layer.

Single source of truth.  All reads for decisions come from here at call
time.  No ambient caches, no markdown, no daily JSON.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

DEFAULT_DB_PATH = os.path.expanduser("~/.plansync/dispatch.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,
    domain          TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    source_ref      TEXT DEFAULT '',
    path_id         TEXT DEFAULT '',
    "group"         TEXT DEFAULT '',
    trigger_def     TEXT NOT NULL,  -- JSON
    trigger_type    TEXT NOT NULL,  -- calendar|condition|after|compound
    status          TEXT NOT NULL DEFAULT 'watching'
                    CHECK(status IN ('watching','due','done','skipped')),
    due_date        TEXT,           -- date string YYYY-MM-DD
    trigger_fired   TEXT,           -- datetime ISO-8601
    completed_at    TEXT,
    checklist       TEXT DEFAULT '[]',  -- JSON array
    sort_order      INTEGER DEFAULT 0,
    notes           TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_domain_status ON items(domain, status);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);

CREATE TABLE IF NOT EXISTS event_log (
    id              TEXT PRIMARY KEY,
    batch_id        TEXT,
    event_type      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    domain          TEXT,
    item_id         TEXT,
    source_ref      TEXT,
    source          TEXT DEFAULT 'system',
    old_values      TEXT,  -- JSON
    new_values      TEXT,  -- JSON
    payload         TEXT   -- JSON
);

CREATE INDEX IF NOT EXISTS idx_events_batch ON event_log(batch_id);
CREATE INDEX IF NOT EXISTS idx_events_item ON event_log(item_id);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON event_log(event_type, timestamp);

CREATE TABLE IF NOT EXISTS weather_log (
    id              TEXT PRIMARY KEY,
    location        TEXT NOT NULL,
    weather_date    TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    temp_current    REAL,
    temp_high       REAL,
    temp_low        REAL,
    conditions      TEXT,  -- JSON array
    forecast        TEXT,  -- JSON
    UNIQUE(location, weather_date)
);

CREATE TABLE IF NOT EXISTS conditions_cache (
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL REFERENCES items(id),
    metric          TEXT NOT NULL,
    operator        TEXT NOT NULL,
    value           REAL NOT NULL,
    sustained_days  INTEGER DEFAULT 1,
    current_value   REAL,
    consecutive_days INTEGER DEFAULT 0,
    is_met          INTEGER DEFAULT 0,
    last_evaluated  TEXT,
    UNIQUE(item_id, metric, operator, value, sustained_days)
);
"""


def new_id():
    return uuid4().hex[:12]


def db_path():
    return os.path.expanduser(os.environ.get("DISPATCH_DB", DEFAULT_DB_PATH))


def init_db(path=None):
    path = path or db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return path


@contextmanager
def connect(path=None):
    path = path or db_path()
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for key in ("trigger_def", "checklist", "conditions", "forecast",
                "old_values", "new_values", "payload"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Item CRUD ---

def insert_item(conn, domain, name, trigger_def, **kwargs):
    item_id = new_id()
    now = now_iso()
    trigger_type = trigger_def.get("type", "unknown")
    conn.execute(
        """INSERT INTO items
           (id, domain, name, description, source_ref, path_id, "group",
            trigger_def, trigger_type, status, checklist, sort_order, notes,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'watching', ?, ?, ?, ?, ?)""",
        (
            item_id, domain, name,
            kwargs.get("description", ""),
            kwargs.get("source_ref", ""),
            kwargs.get("path_id", ""),
            kwargs.get("group", ""),
            json.dumps(trigger_def), trigger_type,
            json.dumps(kwargs.get("checklist", [])),
            kwargs.get("sort_order", 0),
            kwargs.get("notes", ""),
            now, now,
        ),
    )
    return item_id


def get_item(conn, item_id):
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return row_to_dict(row)


def get_items(conn, domain=None, status=None):
    clauses, params = [], []
    if domain:
        clauses.append("domain=?")
        params.append(domain)
    if status:
        if isinstance(status, (list, tuple)):
            placeholders = ",".join("?" for _ in status)
            clauses.append(f"status IN ({placeholders})")
            params.extend(status)
        else:
            clauses.append("status=?")
            params.append(status)
    where = " AND ".join(clauses)
    sql = "SELECT * FROM items"
    if where:
        sql += f" WHERE {where}"
    sql += ' ORDER BY domain, "group", sort_order, due_date'
    return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def get_open_items(conn, domain=None):
    return get_items(conn, domain=domain, status=["watching", "due"])


def get_due_items(conn, domain=None, today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    clauses = ["status = 'due'", "due_date <= ?"]
    params = [today]
    if domain:
        clauses.append("domain=?")
        params.append(domain)
    where = " AND ".join(clauses)
    sql = f'SELECT * FROM items WHERE {where} ORDER BY domain, "group", sort_order'
    return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


# --- Event logging ---

def log_event(conn, event_type, batch_id=None, **kwargs):
    event_id = new_id()
    source = kwargs.get("source") or os.environ.get("DISPATCH_CLIENT", "system")
    conn.execute(
        """INSERT INTO event_log
           (id, batch_id, event_type, timestamp, domain, item_id,
            source_ref, source, old_values, new_values, payload)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id, batch_id, event_type, now_iso(),
            kwargs.get("domain"),
            kwargs.get("item_id"),
            kwargs.get("source_ref"),
            source,
            json.dumps(kwargs.get("old_values")) if kwargs.get("old_values") else None,
            json.dumps(kwargs.get("new_values")) if kwargs.get("new_values") else None,
            json.dumps(kwargs.get("payload")) if kwargs.get("payload") else None,
        ),
    )
    return event_id


# --- Status transitions ---

TRANSITIONS = {
    "watching": {"fire": "due", "skip": "skipped", "complete": "done"},
    "due":      {"complete": "done", "skip": "skipped", "defer": "watching",
                 "unfire": "watching"},
    "done":     {"undo": "due"},
    "skipped":  {"undo": "watching"},
}


def transition(conn, item_id, event, batch_id=None, **kwargs):
    item = get_item(conn, item_id)
    if not item:
        raise ValueError(f"Item {item_id} not found")

    current = item["status"]
    allowed = TRANSITIONS.get(current, {})
    if event not in allowed:
        raise ValueError(
            f"Cannot {event} item in status '{current}'. "
            f"Allowed: {list(allowed.keys())}"
        )

    new_status = allowed[event]
    now = now_iso()
    updates = {"status": new_status, "updated_at": now}
    old_values = {"status": current}

    if event == "fire":
        updates["trigger_fired"] = now
        updates["due_date"] = kwargs.get("due_date", datetime.now().strftime("%Y-%m-%d"))
    elif event == "complete":
        updates["completed_at"] = now
        if kwargs.get("notes"):
            updates["notes"] = (item.get("notes") or "") + "\n" + kwargs["notes"]
    elif event == "unfire":
        updates["due_date"] = None
        updates["trigger_fired"] = None
        old_values["due_date"] = item.get("due_date")
        old_values["trigger_fired"] = item.get("trigger_fired")
    elif event == "defer":
        new_date = kwargs.get("new_date")
        if not new_date:
            raise ValueError("defer requires new_date")
        updates["due_date"] = None
        updates["trigger_fired"] = None
        old_values["due_date"] = item.get("due_date")
        old_values["trigger_fired"] = item.get("trigger_fired")
        old_tdef = item["trigger_def"]
        new_tdef = _defer_trigger(old_tdef, new_date)
        updates["trigger_def"] = json.dumps(new_tdef)
        updates["trigger_type"] = new_tdef["type"]
    elif event == "undo":
        updates["completed_at"] = None
        if current == "done":
            updates["due_date"] = item.get("due_date")

    set_clause = ", ".join(f'"{k}"=?' if k == "group" else f"{k}=?" for k in updates)
    vals = list(updates.values()) + [item_id]
    conn.execute(f"UPDATE items SET {set_clause} WHERE id=?", vals)

    log_event(
        conn, f"item_{event}ed" if not event.endswith("e") else f"item_{event}d",
        batch_id=batch_id,
        domain=item["domain"],
        item_id=item_id,
        source_ref=item.get("source_ref"),
        old_values=old_values,
        new_values=updates,
        **kwargs,
    )

    # Fire after-triggers when an item completes
    if event == "complete":
        _fire_dependents(conn, item_id, batch_id)

    conn.commit()
    return get_item(conn, item_id)


def _fire_dependents(conn, completed_id, batch_id):
    today = datetime.now().strftime("%Y-%m-%d")
    watching = conn.execute(
        "SELECT * FROM items WHERE status='watching'",
    ).fetchall()
    for row in watching:
        item = row_to_dict(row)
        tdef = item["trigger_def"]
        if tdef.get("type") != "after" or tdef.get("item_ref") != completed_id:
            continue
        fire_date = _after_fire_date(conn, tdef, today)
        if fire_date and fire_date <= today:
            transition(conn, item["id"], "fire", batch_id=batch_id,
                       due_date=fire_date)


def _after_fire_date(conn, tdef, today, parent=None):
    """Date an after-trigger becomes due. None if the parent is not done."""
    ref = parent if parent is not None else get_item(conn, tdef.get("item_ref"))
    if not ref or ref["status"] != "done":
        return None
    offset = int(tdef.get("offset_days") or 0)
    if offset > 0 and ref.get("completed_at"):
        completed = datetime.strptime(ref["completed_at"][:10], "%Y-%m-%d")
        return (completed + timedelta(days=offset)).strftime("%Y-%m-%d")
    return today


def _defer_trigger(tdef, new_date):
    if tdef.get("type") == "calendar":
        return {**tdef, "date": new_date}
    if tdef.get("type") == "condition":
        return {**tdef, "earliest_date": new_date}
    if tdef.get("type") == "compound":
        has_calendar = any(t.get("type") == "calendar" for t in tdef.get("triggers", []))
        if has_calendar:
            return {
                **tdef,
                "triggers": [
                    {**t, "date": new_date} if t.get("type") == "calendar" else t
                    for t in tdef["triggers"]
                ],
            }
    return {
        "type": "compound",
        "op": "and",
        "triggers": [
            {"type": "calendar", "date": new_date},
            tdef,
        ],
    }


# --- Condition helpers ---

def derive_conditions(conn, item_id, trigger_def):
    conn.execute("DELETE FROM conditions_cache WHERE item_id=?", (item_id,))
    _walk_conditions(conn, item_id, trigger_def)


def _walk_conditions(conn, item_id, tdef):
    if tdef.get("type") == "condition":
        for rule in tdef.get("rules", []):
            conn.execute(
                """INSERT OR IGNORE INTO conditions_cache
                   (id, item_id, metric, operator, value, sustained_days)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_id(), item_id, rule["metric"], rule["operator"],
                 rule["value"], rule.get("sustained_days", 1)),
            )
    elif tdef.get("type") == "compound":
        for sub in tdef.get("triggers", []):
            _walk_conditions(conn, item_id, sub)
