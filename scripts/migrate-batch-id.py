#!/usr/bin/env python3
"""One-time migration for Step 34: add batch_id TEXT to activity_log.

batch_id groups every log entry produced by one operation into a single
reversible unit for undo (Step 45). Existing entries stay NULL.

ALTER TABLE ADD COLUMN is enough here (no CHECK change, nullable, no
default), so no table rebuild. Idempotent: skips if the column exists.

Run in-container (or anywhere with the DB path):
    python3 /opt/plansync/scripts/migrate-batch-id.py
"""

import os
import sqlite3
import sys

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/data/plansync/plansync.db")


def main():
    if not os.path.exists(DB_PATH):
        print(f"error: DB not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(activity_log)").fetchall()]
        if "batch_id" in cols:
            print("activity_log.batch_id already exists -- nothing to do")
            return 0
        conn.execute("ALTER TABLE activity_log ADD COLUMN batch_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_batch ON activity_log(batch_id)")
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        print(f"added activity_log.batch_id ({n} existing entries left NULL)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
