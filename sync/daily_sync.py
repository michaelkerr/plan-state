#!/usr/bin/env python3
"""
Deterministic daily sync: weather pull, condition eval, trigger fire,
date cascade, Todoist sync, summary output. Zero LLM tokens.
"""

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

try:
    import requests
except ImportError:  # absent in test/tooling environments; required in the container
    requests = None

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/plansync/plansync.db")
OWM_KEY = os.environ.get("OPENWEATHERMAP_API_KEY", "")
TODOIST_KEY = os.environ.get("TODOIST_API_KEY", "")
# Watching activities dated within this window sync to Todoist ahead of their
# trigger, matching the briefing's 7-day view (see enqueue_todoist_items)
TODOIST_LOOKAHEAD_DAYS = int(os.environ.get("TODOIST_LOOKAHEAD_DAYS", "7"))
OUTPUT_DIR = os.environ.get("PLANSYNC_OUTPUT_DIR", "/opt/plansync/sync-output")

TODAY = date.today()
# Naive UTC, matching the format utcnow() produced (nothing reads these back)
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


class SyncSummary:
    def __init__(self):
        self.triggers_fired = []
        self.dates_cascaded = []
        self.todoist_created = []
        self.todoist_updated = []
        self.todoist_completed = []
        self.overdue = []
        self.errors = []

    def is_empty(self):
        return not any([
            self.triggers_fired, self.dates_cascaded,
            self.todoist_created, self.todoist_updated,
            self.todoist_completed, self.overdue,
        ])

    def to_dict(self):
        return {
            "date": TODAY.isoformat(),
            "triggers_fired": self.triggers_fired,
            "dates_cascaded": self.dates_cascaded,
            "todoist_created": self.todoist_created,
            "todoist_updated": self.todoist_updated,
            "todoist_completed": self.todoist_completed,
            "overdue": self.overdue,
            "errors": self.errors,
        }

    def to_stdout(self):
        # Always emit something: cron output is delivered to Telegram, and an
        # empty quiet day should still produce a heartbeat message.
        if self.is_empty():
            return f"Plan sync {TODAY.isoformat()}: ran clean, no changes."
        lines = ["---"]
        lines.append(f"triggers_fired: {len(self.triggers_fired)}")
        for t in self.triggers_fired:
            lines.append(f'  - "{t["name"]}" ({t["reason"]})')
        lines.append(f"dates_cascaded: {len(self.dates_cascaded)}")
        for d in self.dates_cascaded:
            lines.append(f'  - "{d["name"]}" moved to {d["new_date"]} (was {d["old_date"]})')
        lines.append(f"todoist_created: {len(self.todoist_created)}")
        lines.append(f"todoist_updated: {len(self.todoist_updated)}")
        lines.append(f"todoist_completed: {len(self.todoist_completed)}")
        lines.append(f"overdue: {len(self.overdue)}")
        for o in self.overdue:
            lines.append(f'  - "{o["name"]}" was due {o["due_date"]}')
        lines.append("---")
        return "\n".join(lines)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # No WAL here: unsupported on the exFAT/VirtioFS mount (see init-db.py)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def log_change(conn, item_type, item_id, action, old_value, new_value):
    conn.execute(
        "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source) VALUES (?,?,?,?,?,?)",
        (item_type, item_id, action, json.dumps(old_value), json.dumps(new_value), "cron"),
    )


# ── Step 1: Weather Pull ────────────────────────────────────

def derive_daily_range(current_temp, forecast_data, now_utc):
    """Today's expected (high, low) from the 3-hourly forecast, blended with the
    current reading. A single snapshot can't know the day's range -- a 6 AM run
    would record the morning temp as the 'high'. Forecast entries are UTC;
    'today' means the local calendar day per the response's city.timezone."""
    if not forecast_data or not forecast_data.get("list"):
        return current_temp, current_temp

    tz_offset = timedelta(seconds=forecast_data.get("city", {}).get("timezone", 0))
    today_local = (now_utc + tz_offset).date()

    temps = []
    for entry in forecast_data["list"]:
        dt = entry.get("dt")
        main = entry.get("main", {})
        if dt is None:
            continue
        local_day = (datetime.fromtimestamp(dt, tz=timezone.utc).replace(tzinfo=None) + tz_offset).date()
        if local_day != today_local:
            continue
        for key in ("temp", "temp_min", "temp_max"):
            if main.get(key) is not None:
                temps.append(main[key])

    if current_temp is not None:
        temps.append(current_temp)
    if not temps:
        return current_temp, current_temp
    return max(temps), min(temps)


def pull_weather(conn, summary):
    if not OWM_KEY:
        summary.errors.append("OPENWEATHERMAP_API_KEY not set, skipping weather pull")
        return
    if requests is None:
        summary.errors.append("requests not installed, skipping weather pull")
        return

    locations = conn.execute("SELECT DISTINCT location FROM domains WHERE location IS NOT NULL").fetchall()
    for row in locations:
        loc = row["location"]
        try:
            current = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": loc, "appid": OWM_KEY, "units": "imperial"},
                timeout=15,
            )
            current.raise_for_status()
            cdata = current.json()

            forecast = requests.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={"q": loc, "appid": OWM_KEY, "units": "imperial", "cnt": 40},
                timeout=15,
            )
            forecast.raise_for_status()
            fdata = forecast.json()

            current_temp = cdata.get("main", {}).get("temp")
            temp_high, temp_low = derive_daily_range(current_temp, fdata, NOW)
            weather_desc = cdata.get("weather", [{}])[0].get("main", "")
            rain = cdata.get("rain", {}).get("1h", 0) or 0
            precip_inches = rain * 0.03937

            upsert_weather_row(conn, loc, temp_high, temp_low, weather_desc, precip_inches, json.dumps(fdata))
        except Exception as e:
            summary.errors.append(f"Weather pull failed for {loc}: {e}")


def upsert_weather_row(conn, loc, temp_high, temp_low, conditions, precipitation, forecast_json):
    """One weather row per location per local day. A second run the same day
    (duplicate cron fire, manual verification) refreshes the row instead of
    inserting -- sustained_days trigger evaluation counts rows as days."""
    existing = conn.execute(
        "SELECT id FROM weather_log WHERE location=? AND date(recorded_at, 'localtime') = date('now', 'localtime')",
        (loc,),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE weather_log SET temp_high=?, temp_low=?, conditions=?, precipitation=?,
               forecast_json=?, recorded_at=CURRENT_TIMESTAMP WHERE id=?""",
            (temp_high, temp_low, conditions, precipitation, forecast_json, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO weather_log (location, temp_high, temp_low, soil_temp, conditions, precipitation, forecast_json)
               VALUES (?,?,?,?,?,?,?)""",
            (loc, temp_high, temp_low, None, conditions, precipitation, forecast_json),
        )


# ── Step 2: Condition Evaluation ─────────────────────────────

def evaluate_conditions(conn, summary):
    conditions = conn.execute(
        "SELECT c.*, a.domain_id FROM conditions c JOIN activities a ON c.activity_id = a.id WHERE a.status = 'watching'"
    ).fetchall()

    for cond in conditions:
        cdef = json.loads(cond["definition"]) if isinstance(cond["definition"], str) else cond["definition"]
        ctype = cond["condition_type"]

        domain_loc = conn.execute(
            "SELECT location FROM domains WHERE id=?", (cond["domain_id"],)
        ).fetchone()
        location = domain_loc["location"] if domain_loc else None

        is_met = False
        current_value = None

        if ctype == "temperature" and location:
            is_met, current_value = _eval_temperature(conn, location, cdef)
        elif ctype == "weather_event" and location:
            is_met, current_value = _eval_weather_event(conn, location, cdef)
        elif ctype == "calendar":
            is_met, current_value = _eval_calendar(cdef)
        elif ctype == "dependency":
            is_met, current_value = _eval_dependency(conn, cdef)

        conn.execute(
            "UPDATE conditions SET current_value=?, is_met=?, last_checked=? WHERE id=?",
            (current_value, is_met, NOW.isoformat(), cond["id"]),
        )


def _eval_temperature(conn, location, cdef):
    metric = cdef.get("metric", "soil_temp")
    op = cdef.get("operator", ">=")
    threshold = cdef.get("value", 0)
    sustained = cdef.get("sustained_days", 1)

    col_map = {
        "soil_temp": "soil_temp",
        "daily_high": "temp_high",
        "daily_low": "temp_low",
        "temp_high": "temp_high",
        "temp_low": "temp_low",
    }
    col = col_map.get(metric, "temp_high")

    recent = conn.execute(
        f"SELECT {col} as val FROM weather_log WHERE location=? AND {col} IS NOT NULL ORDER BY recorded_at DESC LIMIT ?",
        (location, sustained),
    ).fetchall()

    if len(recent) < sustained:
        return False, recent[0]["val"] if recent else None

    current = recent[0]["val"]
    check = {">=": lambda v: v >= threshold, "<=": lambda v: v <= threshold,
             ">": lambda v: v > threshold, "<": lambda v: v < threshold,
             "==": lambda v: v == threshold}
    op_fn = check.get(op, lambda v: False)
    met = all(op_fn(r["val"]) for r in recent if r["val"] is not None)
    return met, current


def _eval_weather_event(conn, location, cdef):
    event = cdef.get("event", "")
    latest = conn.execute(
        "SELECT conditions FROM weather_log WHERE location=? ORDER BY recorded_at DESC LIMIT 1",
        (location,),
    ).fetchone()
    if not latest:
        return False, None
    current = latest["conditions"] or ""
    return event.lower() in current.lower(), None


def _eval_calendar(cdef):
    target = cdef.get("date") or cdef.get("after")
    if not target:
        return False, None
    target_date = date.fromisoformat(target)
    return TODAY >= target_date, (TODAY - target_date).days


def _eval_dependency(conn, cdef):
    dep_id = cdef.get("activity_id")
    event = cdef.get("event", "completed")
    if not dep_id:
        return False, None
    dep = conn.execute("SELECT status, completed_at FROM activities WHERE id=?", (dep_id,)).fetchone()
    if not dep:
        return False, None
    if event == "completed":
        return dep["status"] == "completed", None
    return False, None


# ── Step 3: Trigger Evaluation ───────────────────────────────

def evaluate_triggers(conn, summary):
    watching = conn.execute(
        "SELECT * FROM activities WHERE status = 'watching'"
    ).fetchall()

    for act in watching:
        tdef = json.loads(act["trigger_def"]) if isinstance(act["trigger_def"], str) else act["trigger_def"]
        if not tdef:
            continue

        fired, reason = _check_trigger(conn, act, tdef)
        if fired:
            has_prep = conn.execute(
                "SELECT COUNT(*) as cnt FROM steps WHERE activity_id=? AND step_type='prep'", (act["id"],)
            ).fetchone()["cnt"]
            new_status = "preparing" if has_prep > 0 else "active"

            trigger_date = act["trigger_date"] or TODAY.isoformat()
            conn.execute(
                "UPDATE activities SET status=?, trigger_fired=?, trigger_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_status, NOW.isoformat(), trigger_date, act["id"]),
            )
            log_change(conn, "activity", act["id"], "trigger_fire",
                        {"status": "watching"}, {"status": new_status, "reason": reason})

            if trigger_date:
                _cascade_steps(conn, act["id"], trigger_date, summary)

            summary.triggers_fired.append({"name": act["name"], "reason": reason})


def _check_trigger(conn, act, tdef):
    ttype = tdef.get("type")

    if ttype == "calendar":
        target = tdef.get("date")
        if target:
            target_date = date.fromisoformat(target)
            max_prep = conn.execute(
                "SELECT MAX(lead_days) as m FROM steps WHERE activity_id=? AND step_type='prep'",
                (act["id"],),
            ).fetchone()["m"] or 0
            prep_start = target_date - timedelta(days=max_prep)
            if TODAY >= prep_start:
                return True, f"calendar: prep window opened (target {target})"
        return False, ""

    if ttype == "condition":
        conditions = conn.execute(
            "SELECT * FROM conditions WHERE activity_id=?", (act["id"],)
        ).fetchall()
        if not conditions:
            return False, ""
        all_met = all(c["is_met"] for c in conditions)
        if all_met:
            descs = []
            for c in conditions:
                d = json.loads(c["definition"]) if isinstance(c["definition"], str) else c["definition"]
                descs.append(f'{d.get("metric","?")} {d.get("operator","?")} {d.get("value","?")}')
            return True, f"condition: {', '.join(descs)}"
        return False, ""

    if ttype == "dependency":
        met, _ = _eval_dependency(conn, tdef)
        if met:
            return True, f"dependency: {tdef.get('activity_id')} completed"
        return False, ""

    if ttype == "compound":
        op = tdef.get("operator", "AND")
        subs = tdef.get("conditions", [])
        results = []
        reasons = []
        for sub in subs:
            fired, reason = _check_trigger(conn, act, sub)
            results.append(fired)
            if fired:
                reasons.append(reason)
        if op == "AND" and all(results):
            return True, f"compound AND: {'; '.join(reasons)}"
        if op == "OR" and any(results):
            return True, f"compound OR: {'; '.join(reasons)}"
        return False, ""

    return False, ""


def _cascade_steps(conn, activity_id, trigger_date_str, summary):
    trigger_dt = date.fromisoformat(trigger_date_str)
    steps = conn.execute(
        "SELECT * FROM steps WHERE activity_id=? AND status NOT IN ('completed','skipped')",
        (activity_id,),
    ).fetchall()
    for s in steps:
        if s["step_type"] == "prep":
            new_due = (trigger_dt - timedelta(days=s["lead_days"])).isoformat()
        else:
            new_due = (trigger_dt + timedelta(days=s["lead_days"])).isoformat()
        old_due = s["due_date"]
        if new_due != old_due:
            conn.execute("UPDATE steps SET due_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_due, s["id"]))
            log_change(conn, "step", s["id"], "date_cascade", {"due_date": old_due}, {"due_date": new_due})
            summary.dates_cascaded.append({"name": s["name"], "old_date": old_due, "new_date": new_due})


# ── Step 4: Date Re-cascade ─────────────────────────────────

def reestimate_dates(conn, summary):
    watching = conn.execute(
        "SELECT a.*, d.location FROM activities a JOIN domains d ON a.domain_id=d.id WHERE a.status='watching' AND a.trigger_type='condition'"
    ).fetchall()

    for act in watching:
        location = act["location"]
        if not location:
            continue

        tdef = json.loads(act["trigger_def"]) if isinstance(act["trigger_def"], str) else act["trigger_def"]
        estimated = _estimate_trigger_date(conn, location, tdef)
        if estimated and estimated != act["trigger_date"]:
            old_date = act["trigger_date"]
            conn.execute("UPDATE activities SET trigger_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (estimated, act["id"]))
            log_change(conn, "activity", act["id"], "date_cascade",
                        {"trigger_date": old_date}, {"trigger_date": estimated})
            _cascade_steps(conn, act["id"], estimated, summary)


def _estimate_trigger_date(conn, location, tdef):
    """Rough estimate based on forecast data. Returns ISO date string or None."""
    if not tdef:
        return None

    metric = None
    threshold = None
    op = ">="
    sustained = 1

    if tdef.get("type") == "condition":
        for key in ("metric", "operator", "value", "sustained_days"):
            if key == "metric":
                metric = tdef.get(key)
            elif key == "operator":
                op = tdef.get(key, ">=")
            elif key == "value":
                threshold = tdef.get(key)
            elif key == "sustained_days":
                sustained = tdef.get(key, 1)
        if tdef.get("all"):
            first = tdef["all"][0] if tdef["all"] else {}
            metric = first.get("metric")
            threshold = first.get("value")
            op = first.get("operator", ">=")
            sustained = first.get("sustained_days", 1)

    if not metric or threshold is None:
        return None

    latest = conn.execute(
        "SELECT forecast_json FROM weather_log WHERE location=? AND forecast_json IS NOT NULL ORDER BY recorded_at DESC LIMIT 1",
        (location,),
    ).fetchone()

    if not latest or not latest["forecast_json"]:
        return None

    try:
        fdata = json.loads(latest["forecast_json"])
    except (json.JSONDecodeError, TypeError):
        return None

    check = {">=": lambda v: v >= threshold, "<=": lambda v: v <= threshold,
             ">": lambda v: v > threshold, "<": lambda v: v < threshold}
    op_fn = check.get(op, lambda v: False)

    col_key = {"daily_high": "temp_max", "temp_high": "temp_max",
               "daily_low": "temp_min", "temp_low": "temp_min"}.get(metric, "temp")

    for entry in fdata.get("list", []):
        temp = entry.get("main", {}).get(col_key, entry.get("main", {}).get("temp"))
        if temp is not None and op_fn(temp):
            dt_txt = entry.get("dt_txt", "")
            if dt_txt:
                return dt_txt[:10]

    return None


# ── Step 5: Overdue Check ────────────────────────────────────

def check_overdue(conn, summary):
    overdue = conn.execute(
        """SELECT s.*, a.name as activity_name FROM steps s
           JOIN activities a ON s.activity_id = a.id
           WHERE s.status IN ('pending','due') AND s.due_date < ? AND s.due_date IS NOT NULL""",
        (TODAY.isoformat(),),
    ).fetchall()

    for s in overdue:
        if s["status"] != "due":
            conn.execute("UPDATE steps SET status='due', updated_at=CURRENT_TIMESTAMP WHERE id=?", (s["id"],))
        summary.overdue.append({
            "name": f'{s["activity_name"]}: {s["name"]}',
            "due_date": s["due_date"],
        })


# ── Step 6: Todoist Sync ─────────────────────────────────────

# Unified v1 API -- REST v2 was sunset (410 Gone) July 2026
TODOIST_API = "https://api.todoist.com/api/v1"


def task_content(group_name, item_name):
    return f"{group_name}: {item_name}" if group_name else item_name


def task_is_completed(task):
    # v1 uses "checked"; tolerate the old REST v2 "is_completed" just in case
    return bool(task.get("checked") or task.get("is_completed"))


def enqueue_todoist_items(conn):
    """Reconciliation pass: queue Todoist task creation for anything actionable
    that has no sync row yet. Idempotent; runs regardless of API availability so
    the queue is ready when sync happens. Nothing else writes pending_create.

    Fired activities (preparing/active) enqueue with all their dated steps.
    Watching activities dated within TODOIST_LOOKAHEAD_DAYS also enqueue, with
    only their steps due inside the horizon, so Todoist shows the same week
    ahead as the Telegram briefing; the rest arrives when the trigger fires."""
    horizon = (TODAY + timedelta(days=TODOIST_LOOKAHEAD_DAYS)).isoformat()
    conn.execute(
        """INSERT INTO todoist_sync (plan_item_id, plan_item_type, sync_status)
           SELECT a.id, 'activity', 'pending_create'
           FROM activities a
           WHERE (a.status IN ('preparing','active')
                  OR (a.status = 'watching' AND a.trigger_date IS NOT NULL
                      AND a.trigger_date <= :horizon))
             AND NOT EXISTS (
               SELECT 1 FROM todoist_sync ts
               WHERE ts.plan_item_id = a.id AND ts.plan_item_type = 'activity')""",
        {"horizon": horizon},
    )
    conn.execute(
        """INSERT INTO todoist_sync (plan_item_id, plan_item_type, sync_status)
           SELECT s.id, 'step', 'pending_create'
           FROM steps s
           JOIN activities a ON s.activity_id = a.id
           WHERE (a.status IN ('preparing','active')
                  OR (a.status = 'watching' AND a.trigger_date IS NOT NULL
                      AND a.trigger_date <= :horizon AND s.due_date <= :horizon))
             AND s.status IN ('pending','due')
             AND s.due_date IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM todoist_sync ts
               WHERE ts.plan_item_id = s.id AND ts.plan_item_type = 'step')""",
        {"horizon": horizon},
    )


def todoist_sync(conn, summary):
    if not TODOIST_KEY:
        summary.errors.append("TODOIST_API_KEY not set, skipping Todoist sync")
        return
    if requests is None:
        summary.errors.append("requests not installed, skipping Todoist sync")
        return

    headers = {"Authorization": f"Bearer {TODOIST_KEY}", "Content-Type": "application/json"}

    _todoist_create(conn, headers, summary)
    _todoist_update(conn, headers, summary)
    _todoist_close(conn, headers, summary)
    _todoist_poll_completions(conn, headers, summary)


def _get_or_create_project(headers, project_name):
    cursor = None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{TODOIST_API}/projects", headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for p in data.get("results", []):
            if p["name"] == project_name:
                return p["id"]
        cursor = data.get("next_cursor")
        if not cursor:
            break

    resp = requests.post(
        f"{TODOIST_API}/projects", headers=headers, json={"name": project_name}, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _todoist_create(conn, headers, summary):
    pending = conn.execute(
        """SELECT ts.*, COALESCE(a.name, s.name) as item_name,
                  COALESCE(a.description, s.description) as item_desc,
                  COALESCE(a.trigger_date, s.due_date) as item_due,
                  COALESCE(a.group_name, (SELECT group_name FROM activities WHERE id = s.activity_id)) as group_name,
                  d.name as domain_name
           FROM todoist_sync ts
           LEFT JOIN activities a ON ts.plan_item_id = a.id AND ts.plan_item_type = 'activity'
           LEFT JOIN steps s ON ts.plan_item_id = s.id AND ts.plan_item_type = 'step'
           LEFT JOIN domains d ON COALESCE(a.domain_id, (SELECT domain_id FROM activities WHERE id = s.activity_id)) = d.id
           WHERE ts.sync_status = 'pending_create'"""
    ).fetchall()

    for item in pending:
        due = item["item_due"]
        if not due:
            continue

        project_name = item["domain_name"] or "Plan Sync"
        try:
            project_id = _get_or_create_project(headers, project_name)
            task_data = {
                "content": task_content(item["group_name"], item["item_name"]),
                "description": item["item_desc"] or "",
                "due_date": due,
                "project_id": project_id,
            }
            resp = requests.post(f"{TODOIST_API}/tasks", headers=headers, json=task_data, timeout=15)
            resp.raise_for_status()
            task = resp.json()

            conn.execute(
                "UPDATE todoist_sync SET todoist_task_id=?, todoist_project=?, last_synced=?, sync_status='synced' WHERE plan_item_id=? AND plan_item_type=?",
                (task["id"], project_id, NOW.isoformat(), item["plan_item_id"], item["plan_item_type"]),
            )
            summary.todoist_created.append(item["item_name"])
        except Exception as e:
            summary.errors.append(f"Todoist create failed for {item['item_name']}: {e}")


def _todoist_update(conn, headers, summary):
    pending = conn.execute(
        """SELECT ts.*, COALESCE(a.name, s.name) as item_name,
                  COALESCE(a.trigger_date, s.due_date) as item_due
           FROM todoist_sync ts
           LEFT JOIN activities a ON ts.plan_item_id = a.id AND ts.plan_item_type = 'activity'
           LEFT JOIN steps s ON ts.plan_item_id = s.id AND ts.plan_item_type = 'step'
           WHERE ts.sync_status = 'pending_update' AND ts.todoist_task_id IS NOT NULL"""
    ).fetchall()

    for item in pending:
        try:
            task_data = {"due_date": item["item_due"]}
            resp = requests.post(
                f"{TODOIST_API}/tasks/{item['todoist_task_id']}",
                headers=headers, json=task_data, timeout=15,
            )
            resp.raise_for_status()

            conn.execute(
                "UPDATE todoist_sync SET last_synced=?, sync_status='synced' WHERE plan_item_id=? AND plan_item_type=?",
                (NOW.isoformat(), item["plan_item_id"], item["plan_item_type"]),
            )
            summary.todoist_updated.append(item["item_name"])
        except Exception as e:
            summary.errors.append(f"Todoist update failed for {item['item_name']}: {e}")


def _todoist_close(conn, headers, summary):
    pending = conn.execute(
        """SELECT ts.*, COALESCE(a.name, s.name) as item_name
           FROM todoist_sync ts
           LEFT JOIN activities a ON ts.plan_item_id = a.id AND ts.plan_item_type = 'activity'
           LEFT JOIN steps s ON ts.plan_item_id = s.id AND ts.plan_item_type = 'step'
           WHERE ts.sync_status = 'pending_close' AND ts.todoist_task_id IS NOT NULL"""
    ).fetchall()

    for item in pending:
        try:
            resp = requests.post(
                f"{TODOIST_API}/tasks/{item['todoist_task_id']}/close",
                headers=headers, timeout=15,
            )
            resp.raise_for_status()

            conn.execute(
                "UPDATE todoist_sync SET last_synced=?, sync_status='synced' WHERE plan_item_id=? AND plan_item_type=?",
                (NOW.isoformat(), item["plan_item_id"], item["plan_item_type"]),
            )
            summary.todoist_completed.append(item["item_name"])
        except Exception as e:
            summary.errors.append(f"Todoist close failed for {item['item_name']}: {e}")


def _todoist_poll_completions(conn, headers, summary):
    # Skip plan items already completed locally — otherwise every past
    # completion is re-polled, re-logged, and re-reported on every run.
    synced = conn.execute(
        """SELECT ts.*, COALESCE(a.name, s.name) as item_name
           FROM todoist_sync ts
           LEFT JOIN activities a ON ts.plan_item_id = a.id AND ts.plan_item_type = 'activity'
           LEFT JOIN steps s ON ts.plan_item_id = s.id AND ts.plan_item_type = 'step'
           WHERE ts.sync_status = 'synced' AND ts.todoist_task_id IS NOT NULL
             AND COALESCE(a.status, s.status) NOT IN ('completed', 'skipped')"""
    ).fetchall()

    for item in synced:
        try:
            resp = requests.get(
                f"{TODOIST_API}/tasks/{item['todoist_task_id']}",
                headers=headers, timeout=15,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            task = resp.json()

            if task_is_completed(task):
                now_str = NOW.isoformat()
                if item["plan_item_type"] == "activity":
                    conn.execute(
                        "UPDATE activities SET status='completed', completed_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status != 'completed'",
                        (now_str, item["plan_item_id"]),
                    )
                    log_change(conn, "activity", item["plan_item_id"], "status_change",
                                {"status": "active"}, {"status": "completed", "source": "todoist"})
                elif item["plan_item_type"] == "step":
                    conn.execute(
                        "UPDATE steps SET status='completed', completed_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status != 'completed'",
                        (now_str, item["plan_item_id"]),
                    )
                    log_change(conn, "step", item["plan_item_id"], "status_change",
                                {"status": "due"}, {"status": "completed", "source": "todoist"})
                summary.todoist_completed.append(item["item_name"])
        except Exception as e:
            summary.errors.append(f"Todoist poll failed for {item['plan_item_id']}: {e}")


# ── Step 7: Summary Output ──────────────────────────────────

def save_output(summary):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{TODAY.isoformat()}.json")
    with open(path, "w") as f:
        json.dump(summary.to_dict(), f, indent=2, default=str)


# ── Main ─────────────────────────────────────────────────────

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    summary = SyncSummary()
    conn = get_db()

    try:
        pull_weather(conn, summary)
        conn.commit()

        evaluate_conditions(conn, summary)
        conn.commit()

        evaluate_triggers(conn, summary)
        conn.commit()

        reestimate_dates(conn, summary)
        conn.commit()

        enqueue_todoist_items(conn)
        conn.commit()

        todoist_sync(conn, summary)
        conn.commit()

        # After Todoist sync so completions detected this run are not
        # reported (and re-marked) as overdue.
        check_overdue(conn, summary)
        conn.commit()

        save_output(summary)
    except Exception as e:
        summary.errors.append(f"Fatal: {e}")
        conn.rollback()
    finally:
        conn.close()

    stdout = summary.to_stdout()
    if stdout:
        print(stdout)

    if summary.errors:
        for err in summary.errors:
            print(f"ERROR: {err}", file=sys.stderr)

    sys.exit(1 if summary.errors else 0)


if __name__ == "__main__":
    main()
