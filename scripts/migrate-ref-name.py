#!/usr/bin/env python3
"""One-time migration for Step 46: add activities.ref_name (stable identity),
backfill slugified names (uniquified per domain), create the unique index.

Idempotent: skips if the column exists.

Run in-container:
    python3 /opt/plansync/scripts/migrate-ref-name.py
"""

import os
import sqlite3
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from plansync.engine import slugify  # noqa: E402

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/data/plansync/plansync.db")


def main():
    if not os.path.exists(DB_PATH):
        print(f"error: DB not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(activities)").fetchall()]
        if "ref_name" in cols:
            print("activities.ref_name already exists -- nothing to do")
            return 0
        conn.execute("ALTER TABLE activities ADD COLUMN ref_name TEXT")
        taken_by_domain = {}
        rows = conn.execute("SELECT id, domain_id, name FROM activities ORDER BY created_at, id").fetchall()
        for r in rows:
            taken = taken_by_domain.setdefault(r["domain_id"], set())
            base = slugify(r["name"])
            ref = base
            n = 2
            while ref in taken:
                ref = f"{base}-{n}"
                n += 1
            taken.add(ref)
            conn.execute("UPDATE activities SET ref_name=? WHERE id=?", (ref, r["id"]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_ref ON activities(domain_id, ref_name)")
        conn.commit()
        print(f"added activities.ref_name, backfilled {len(rows)} rows, unique index created")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
