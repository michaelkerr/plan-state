#!/usr/bin/env python3
"""Reads today's sync output and upcoming data for the LLM morning briefing."""

import json
import os
import sqlite3
from datetime import date, timedelta

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/plansync/plansync.db")
OUTPUT_DIR = os.environ.get("PLANSYNC_OUTPUT_DIR", "/opt/plansync/sync-output")
TODAY = date.today().isoformat()
CUTOFF = (date.today() + timedelta(days=14)).isoformat()


def query_db(sql, params=()):
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


print(f"=== Daily Sync Summary ({TODAY}) ===")
sync_file = os.path.join(OUTPUT_DIR, f"{TODAY}.json")
if os.path.exists(sync_file):
    with open(sync_file) as f:
        print(f.read())
else:
    print("No sync output for today.")

print("\n=== Upcoming 14 Days ===")
activities = query_db(
    """SELECT a.name as activity, a.status, a.trigger_date,
              d.name as domain, a.description
       FROM activities a
       JOIN domains d ON a.domain_id = d.id
       WHERE a.status IN ('watching','preparing','active')
         AND (a.trigger_date <= ? OR a.trigger_date IS NULL)
       ORDER BY a.trigger_date NULLS LAST""",
    (CUTOFF,),
)
print(json.dumps(activities, indent=2, default=str))

print("\n=== Due Steps ===")
steps = query_db(
    """SELECT s.name as step, s.due_date, s.status,
              a.name as activity, d.name as domain
       FROM steps s
       JOIN activities a ON s.activity_id = a.id
       JOIN domains d ON a.domain_id = d.id
       WHERE s.status IN ('pending','due')
         AND s.due_date <= ?
         AND s.due_date IS NOT NULL
       ORDER BY s.due_date""",
    (CUTOFF,),
)
print(json.dumps(steps, indent=2, default=str))

print("\n=== Latest Weather ===")
weather = query_db(
    """SELECT location, temp_high, temp_low, soil_temp, conditions,
              precipitation, recorded_at
       FROM weather_log
       WHERE recorded_at >= date('now', '-1 day')
       ORDER BY recorded_at DESC""",
)
print(json.dumps(weather, indent=2, default=str))
