#!/usr/bin/env python3
"""One-time migration for Step 45: widen activity_log.action CHECK to allow
'undo'.

SQLite enforces the CHECK stored in the live table's DDL, so updating
schema.sql alone is not enough -- the table must be rebuilt. Idempotent:
skips if the live DDL already allows 'undo'.

Run in-container:
    python3 /opt/plansync/scripts/migrate-undo-action.py
"""

import os
import sqlite3
import sys

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/data/plansync/plansync.db")

NEW_DDL = """
CREATE TABLE activity_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
  item_type       TEXT NOT NULL CHECK(item_type IN ('domain','activity','step','condition')),
  item_id         TEXT NOT NULL,
  action          TEXT NOT NULL CHECK(action IN ('status_change','date_cascade','trigger_fire','manual_update','created','observation','undo')),
  old_value       JSON,
  new_value       JSON,
  source          TEXT NOT NULL CHECK(source IN ('cron','hermes','claude','human')),
  batch_id        TEXT
)
"""


def main():
    if not os.path.exists(DB_PATH):
        print(f"error: DB not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB_PATH)
    try:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='activity_log'"
        ).fetchone()[0]
        if "'undo'" in ddl:
            print("activity_log.action already allows 'undo' -- nothing to do")
            return 0
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute("ALTER TABLE activity_log RENAME TO activity_log_old")
        conn.execute(NEW_DDL)
        conn.execute(
            "INSERT INTO activity_log (id, timestamp, item_type, item_id, action, old_value, new_value, source, batch_id) "
            "SELECT id, timestamp, item_type, item_id, action, old_value, new_value, source, batch_id FROM activity_log_old"
        )
        conn.execute("DROP TABLE activity_log_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_item ON activity_log(item_type, item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_batch ON activity_log(batch_id)")
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        print(f"widened activity_log.action CHECK to include 'undo' ({n} entries preserved)")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
