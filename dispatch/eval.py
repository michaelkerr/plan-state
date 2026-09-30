"""dispatch.eval — trigger evaluation and weather pull.

Deterministic (zero LLM tokens).  Called hourly by cron.
Pulls weather, evaluates conditions, fires triggers, checks overdue.
"""

import json
import os
from datetime import datetime, timedelta

import requests

from dispatch.store import (
    connect, row_to_dict, new_id, now_iso,
    get_items, transition, derive_conditions, log_event,
)

OWM_KEY = os.environ.get("OWM_API_KEY", "")
OWM_BASE = "https://api.openweathermap.org/data/2.5"


# --- Weather ---

def pull_weather(conn, location, today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    if not OWM_KEY:
        return {"skipped": "OWM_API_KEY not set"}

    current = _fetch_current(location)
    forecast = _fetch_forecast(location)

    high, low = _derive_daily_range(forecast, today)
    if current.get("main"):
        temp = current["main"].get("temp")
        if temp is not None:
            if high is None or temp > high:
                high = temp
            if low is None or temp < low:
                low = temp

    conn.execute(
        """INSERT INTO weather_log
           (id, location, weather_date, recorded_at,
            temp_current, temp_high, temp_low, conditions, forecast)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(location, weather_date) DO UPDATE SET
            recorded_at=excluded.recorded_at,
            temp_current=excluded.temp_current,
            temp_high=MAX(COALESCE(weather_log.temp_high, excluded.temp_high), excluded.temp_high),
            temp_low=MIN(COALESCE(weather_log.temp_low, excluded.temp_low), excluded.temp_low),
            conditions=excluded.conditions,
            forecast=excluded.forecast""",
        (
            new_id(), location, today, now_iso(),
            current.get("main", {}).get("temp"),
            high, low,
            json.dumps(_extract_conditions(current)),
            json.dumps(forecast.get("list", [])[:8]),
        ),
    )
    conn.commit()

    log_event(
        conn, "weather_snapshot",
        domain=None,
        payload={"location": location, "high": high, "low": low,
                 "conditions": _extract_conditions(current)},
    )

    return {"location": location, "date": today, "high": high, "low": low}


def _fetch_current(location):
    try:
        resp = requests.get(
            f"{OWM_BASE}/weather",
            params={"q": location, "appid": OWM_KEY, "units": "imperial"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def _fetch_forecast(location):
    try:
        resp = requests.get(
            f"{OWM_BASE}/forecast",
            params={"q": location, "appid": OWM_KEY, "units": "imperial"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def _derive_daily_range(forecast_data, today):
    high, low = None, None
    for entry in forecast_data.get("list", []):
        dt_txt = entry.get("dt_txt", "")
        if dt_txt.startswith(today):
            temp = entry.get("main", {}).get("temp")
            if temp is not None:
                if high is None or temp > high:
                    high = temp
                if low is None or temp < low:
                    low = temp
    return high, low


def _extract_conditions(current):
    return [w.get("main", "") for w in current.get("weather", [])]


# --- Condition evaluation ---

def evaluate_conditions(conn, location):
    today = datetime.now().strftime("%Y-%m-%d")
    weather = conn.execute(
        "SELECT * FROM weather_log WHERE location=? AND weather_date=?",
        (location, today),
    ).fetchone()
    if not weather:
        return {"skipped": "no weather data for today"}

    weather = row_to_dict(weather)
    metric_values = {
        "daily_high": weather.get("temp_high"),
        "daily_low": weather.get("temp_low"),
        "temp_high": weather.get("temp_high"),
        "temp_low": weather.get("temp_low"),
    }

    rows = conn.execute(
        """SELECT cc.*, i.status FROM conditions_cache cc
           JOIN items i ON cc.item_id = i.id
           WHERE i.status = 'watching'"""
    ).fetchall()

    updated = 0
    for row in rows:
        row = dict(row)
        metric_val = metric_values.get(row["metric"])
        if metric_val is None:
            continue

        met = _check_condition(metric_val, row["operator"], row["value"])
        if met:
            new_consec = row["consecutive_days"] + 1
        else:
            new_consec = 0

        is_met = 1 if new_consec >= row["sustained_days"] else 0

        conn.execute(
            """UPDATE conditions_cache SET
               current_value=?, consecutive_days=?, is_met=?,
               last_evaluated=?
               WHERE id=?""",
            (metric_val, new_consec, is_met, now_iso(), row["id"]),
        )
        updated += 1

    conn.commit()
    return {"evaluated": updated, "date": today}


def _check_condition(actual, operator, threshold):
    ops = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: abs(a - b) < 0.01,
    }
    fn = ops.get(operator)
    return fn(actual, threshold) if fn else False


# --- Trigger evaluation ---

def evaluate_triggers(conn, today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    watching = get_items(conn, status="watching")
    fired = []

    for item in watching:
        tdef = item["trigger_def"]
        should_fire, due_date = _check_trigger(conn, tdef, today, item["id"])
        if should_fire:
            transition(conn, item["id"], "fire",
                       due_date=due_date or today)
            fired.append({"id": item["id"], "name": item["name"],
                          "domain": item["domain"]})

    return {"fired": fired, "date": today}


def _check_trigger(conn, tdef, today, item_id):
    ttype = tdef.get("type")

    if ttype == "calendar":
        target = tdef["date"]
        prep = tdef.get("prep_days", 0)
        fire_date = target
        if prep:
            dt = datetime.strptime(target, "%Y-%m-%d") - timedelta(days=prep)
            fire_date = dt.strftime("%Y-%m-%d")
        if today >= fire_date:
            return True, fire_date
        return False, None

    if ttype == "condition":
        earliest = tdef.get("earliest_date")
        if earliest and today < earliest:
            return False, None
        conditions = conn.execute(
            "SELECT * FROM conditions_cache WHERE item_id=?",
            (item_id,),
        ).fetchall()
        if not conditions:
            return False, None
        all_met = all(dict(c)["is_met"] for c in conditions)
        return all_met, today if all_met else None

    if ttype == "after":
        ref_id = tdef.get("item_ref")
        ref_item = conn.execute(
            "SELECT status, completed_at FROM items WHERE id=?",
            (ref_id,),
        ).fetchone()
        if not ref_item:
            return False, None
        ref_item = dict(ref_item)
        event_type = tdef.get("event", "completed")
        if event_type == "completed" and ref_item["status"] != "done":
            return False, None
        offset = tdef.get("offset_days", 0)
        if offset > 0 and ref_item.get("completed_at"):
            completed = ref_item["completed_at"][:10]
            fire_date = (datetime.strptime(completed, "%Y-%m-%d")
                         + timedelta(days=offset)).strftime("%Y-%m-%d")
            if today < fire_date:
                return False, None
            return True, fire_date
        return True, today

    if ttype == "compound":
        op = tdef.get("op", "and")
        results = []
        for sub in tdef.get("triggers", []):
            ok, date = _check_trigger(conn, sub, today, item_id)
            results.append((ok, date))
        if op == "and":
            if all(r[0] for r in results):
                dates = [r[1] for r in results if r[1]]
                return True, max(dates) if dates else today
            return False, None
        else:
            for ok, date in results:
                if ok:
                    return True, date or today
            return False, None

    return False, None


# --- Full eval pipeline ---

def run_eval(location, today=None):
    results = {}
    with connect() as conn:
        results["weather"] = pull_weather(conn, location, today)
        results["conditions"] = evaluate_conditions(conn, location)
        results["triggers"] = evaluate_triggers(conn, today)
    return results
