#!/usr/bin/env python3
"""Reads today's sync output and upcoming data for the LLM morning briefing."""

import json
import os
import sqlite3
from datetime import date, timedelta

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/data/plansync/plansync.db")
OUTPUT_DIR = os.environ.get("PLANSYNC_OUTPUT_DIR", "/opt/plansync/sync-output")
TODAY = date.today().isoformat()
WEEK_CUTOFF = (date.today() + timedelta(days=7)).isoformat()


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

# The sync JSON above resets at midnight, so a trigger that fired midday
# yesterday would vanish from it by this morning. activity_log is the source
# of truth for the "what happened" narrative -- pull the last 24h directly.
print("\n=== Fired Since Yesterday (last 24h) ===")
fires = query_db(
    """SELECT l.timestamp,
              a.name as activity, a.group_name, d.name as domain,
              json_extract(l.new_value, '$.status') as new_status,
              json_extract(l.new_value, '$.reason') as reason
       FROM activity_log l
       JOIN activities a ON a.id = l.item_id
       JOIN domains d ON a.domain_id = d.id
       WHERE l.action = 'trigger_fire'
         AND l.timestamp >= datetime('now', '-1 day')
       ORDER BY l.timestamp""",
)
print(json.dumps(fires, indent=2, default=str))

print("\n=== Due Today or Overdue ===")
steps = query_db(
    """SELECT s.name as step, s.due_date, s.status,
              a.name as activity, a.group_name, d.name as domain
       FROM steps s
       JOIN activities a ON s.activity_id = a.id
       JOIN domains d ON a.domain_id = d.id
       WHERE s.status IN ('pending','due')
         AND s.due_date <= ?
         AND s.due_date IS NOT NULL
         AND a.status IN ('watching','preparing','active')
       ORDER BY s.due_date""",
    (TODAY,),
)
print(json.dumps(steps, indent=2, default=str))

print("\n=== This Week (next 7 days) ===")
activities = query_db(
    """SELECT a.name as activity, a.group_name, a.status, a.trigger_date,
              d.name as domain
       FROM activities a
       JOIN domains d ON a.domain_id = d.id
       WHERE a.status IN ('watching','preparing','active')
         AND a.trigger_date IS NOT NULL
         AND a.trigger_date <= ?
       ORDER BY d.name, a.group_name NULLS LAST, a.trigger_date""",
    (WEEK_CUTOFF,),
)
print(json.dumps(activities, indent=2, default=str))

steps = query_db(
    """SELECT s.name as step, s.due_date,
              a.name as activity, a.group_name, d.name as domain
       FROM steps s
       JOIN activities a ON s.activity_id = a.id
       JOIN domains d ON a.domain_id = d.id
       WHERE s.status IN ('pending','due')
         AND s.due_date > ? AND s.due_date <= ?
       ORDER BY s.due_date""",
    (TODAY, WEEK_CUTOFF),
)
print(json.dumps(steps, indent=2, default=str))

print("\n=== Recent Observations (last 7 days) ===")
observations = query_db(
    """SELECT l.timestamp,
              json_extract(l.new_value, '$.text') as observation,
              d.name as domain
       FROM activity_log l
       LEFT JOIN domains d ON d.id = json_extract(l.new_value, '$.domain_id')
       WHERE l.action = 'observation'
         AND l.timestamp >= datetime('now', '-7 days')
       ORDER BY l.timestamp DESC""",
)
print(json.dumps(observations, indent=2, default=str))

print("\n=== Latest Weather ===")
weather = query_db(
    """SELECT location, temp_high, temp_low, conditions,
              precipitation, recorded_at
       FROM weather_log
       WHERE recorded_at >= date('now', '-1 day')
       ORDER BY recorded_at DESC""",
)
print(json.dumps(weather, indent=2, default=str))
