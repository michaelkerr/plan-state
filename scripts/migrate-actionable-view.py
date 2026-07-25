#!/usr/bin/env python3
"""One-time migration for Step 39: create the open_steps and actionable_items
views on the live DB.

Views are stored DDL, so schema.sql changes don't reach an existing DB.
Idempotent by design: drops and recreates both views (views hold no data),
so re-running after a view-definition change is also the upgrade path.

Run in-container:
    python3 /opt/plansync/scripts/migrate-actionable-view.py
"""

import os
import re
import sqlite3
import sys

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/data/plansync/plansync.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


def main():
    if not os.path.exists(DB_PATH):
        print(f"error: DB not found at {DB_PATH}", file=sys.stderr)
        return 1

    # The view DDL lives in schema.sql (single source of truth) -- extract it
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    views = re.findall(r"CREATE VIEW IF NOT EXISTS (\w+) AS.*?;", schema, re.DOTALL)
    ddls = re.findall(r"CREATE VIEW IF NOT EXISTS \w+ AS.*?;", schema, re.DOTALL)
    expected = {"open_steps", "actionable_items", "open_activities"}
    if not expected <= set(views):
        print(f"error: schema.sql views {views} missing some of {sorted(expected)}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        for name in views:
            conn.execute(f"DROP VIEW IF EXISTS {name}")
        for ddl in ddls:
            conn.execute(ddl)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM actionable_items").fetchone()[0]
        print(f"created views {', '.join(views)} ({n} items actionable now)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
