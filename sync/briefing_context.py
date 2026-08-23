#!/usr/bin/env python3
"""Reads sync output and upcoming plan data for the LLM morning briefing.

"What's due" comes from the shared view layer (engine.get_actionable_items /
get_open_activities) -- the same definition the evening nudge and MCP server
use. Narrative/context sections (sync JSON, 24h fires, observations, weather)
have their own queries here.
"""

import json
import os
import sys
from datetime import date, timedelta

from plansync import engine

OUTPUT_DIR = os.environ.get("PLANSYNC_OUTPUT_DIR", "/opt/data/plansync/sync-output")
TODAY = date.today().isoformat()
WEEK_CUTOFF = (date.today() + timedelta(days=7)).isoformat()


def main():
    print(f"=== Daily Sync Summary ({TODAY}) ===")
    sync_file = os.path.join(OUTPUT_DIR, f"{TODAY}.json")
    if os.path.exists(sync_file):
        with open(sync_file) as f:
            print(f.read())
    else:
        print("No sync output for today.")

    if not os.path.exists(engine.db_path()):
        print("\nNo database found.")
        return

    with engine.connect() as conn:
        # The sync JSON above resets at midnight, so a trigger that fired
        # midday yesterday would vanish from it by this morning. activity_log
        # is the source of truth for the "what happened" narrative.
        print("\n=== Fired Since Yesterday (last 24h) ===")
        fires = conn.execute(
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
        ).fetchall()
        print(json.dumps([dict(r) for r in fires], indent=2, default=str))

        print("\n=== Due Today or Overdue ===")
        due_now = [
            {"step": i["step_name"], "due_date": i["due_date"], "status": i["step_status"],
             "activity": i["activity_name"], "group_name": i["group_name"], "domain": i["domain_name"]}
            for i in engine.get_actionable_items(conn, as_of_date=TODAY)
        ]
        print(json.dumps(due_now, indent=2, default=str))

        print("\n=== This Week (next 7 days) ===")
        week_acts = engine.get_open_activities(conn, through_date=WEEK_CUTOFF)
        week_acts.sort(key=lambda a: (a["domain_name"], a["group_name"] is None,
                                      a["group_name"] or "", a["trigger_date"]))
        print(json.dumps([
            {"activity": a["activity_name"], "group_name": a["group_name"],
             "status": a["activity_status"], "trigger_date": a["trigger_date"],
             "domain": a["domain_name"]}
            for a in week_acts
        ], indent=2, default=str))

        week_steps = [
            {"step": i["step_name"], "due_date": i["due_date"],
             "activity": i["activity_name"], "group_name": i["group_name"], "domain": i["domain_name"]}
            for i in engine.get_actionable_items(conn, as_of_date=WEEK_CUTOFF)
            if i["due_date"] > TODAY
        ]
        print(json.dumps(week_steps, indent=2, default=str))

        print("\n=== Recent Observations (last 7 days) ===")
        observations = conn.execute(
            """SELECT l.timestamp,
                      json_extract(l.new_value, '$.text') as observation,
                      d.name as domain
               FROM activity_log l
               LEFT JOIN domains d ON d.id = l.item_id
               WHERE l.action = 'observation'
                 AND l.item_type = 'domain'
                 AND l.timestamp >= datetime('now', '-7 days')
               ORDER BY l.timestamp DESC""",
        ).fetchall()
        print(json.dumps([dict(r) for r in observations], indent=2, default=str))

        print("\n=== Latest Weather ===")
        weather = conn.execute(
            """SELECT location, temp_high, temp_low, conditions,
                      precipitation, recorded_at
               FROM weather_log
               WHERE recorded_at >= date('now', '-1 day')
               ORDER BY recorded_at DESC""",
        ).fetchall()
        print(json.dumps([dict(r) for r in weather], indent=2, default=str))


if __name__ == "__main__":
    main()
