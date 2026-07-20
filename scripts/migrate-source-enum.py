#!/usr/bin/env python3
"""One-time migration for Step 27: widen the activity_log.source CHECK
constraint to allow 'claude' and 'human'.

SQLite enforces the CHECK stored in the live table's DDL on every insert,
so updating schema.sql alone is not enough -- the table must be rebuilt.
Idempotent: skips if the live DDL already allows 'claude'.

Run in-container (or anywhere with the DB path):
    python3 /opt/plansync/scripts/migrate-source-enum.py
"""

import os
import sqlite3
import sys

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/plansync/plansync.db")

NEW_DDL = """
CREATE TABLE activity_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
  item_type       TEXT NOT NULL CHECK(item_type IN ('domain','activity','step','condition')),
  item_id         TEXT NOT NULL,
  action          TEXT NOT NULL CHECK(action IN ('status_change','date_cascade','trigger_fire','manual_update','created','observation')),
  old_value       JSON,
  new_value       JSON,
  source          TEXT NOT NULL CHECK(source IN ('cron','hermes','claude','human'))
)
"""


def main():
    if not os.path.exists(DB_PATH):
        print(f"error: no database at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='activity_log'"
        ).fetchone()[0]
        if "'claude'" in ddl:
            print("activity_log already allows 'claude' -- nothing to do")
            return 0
        before = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        conn.execute("BEGIN")
        conn.execute("ALTER TABLE activity_log RENAME TO activity_log_old")
        conn.execute(NEW_DDL)
        conn.execute("INSERT INTO activity_log SELECT * FROM activity_log_old")
        conn.execute("DROP TABLE activity_log_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_item ON activity_log(item_type, item_id)")
        after = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        if after != before:
            conn.execute("ROLLBACK")
            print(f"error: row count mismatch ({before} -> {after}), rolled back", file=sys.stderr)
            return 1
        conn.execute("COMMIT")
        print(f"migrated activity_log ({after} rows) -- source now allows cron/hermes/claude/human")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
