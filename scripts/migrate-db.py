#!/usr/bin/env python3
"""Step 25 migration: rebuild the plansync DB against the current schema and
relocate it off the exFAT/VirtioFS mount.

Rebuild-and-copy: creates a fresh DB at --dest from schema.sql (WAL mode --
the new home is APFS-backed), copies every row, and applies the accumulated
Step 21-23 schema changes in flight:
  - todoist_sync table dropped
  - activities: recurrence column dropped, 'deferred' statuses -> 'watching'
  - steps: condition column dropped
  - weather_log: soil_temp dropped; weather_date derived from recorded_at
    (local day) with UNIQUE(location, weather_date) enforced
  - conditions: re-derived from trigger_def, verified at parity against the
    hand-authored rows, with evaluation state (is_met/current_value/
    last_checked) carried over per matching definition

The source file is left untouched (it is the rollback path). Verifies row
counts, parity, integrity_check, and foreign_key_check; exits nonzero and
removes the partial dest on any failure.

Run in-container:
    python3 /opt/plansync/scripts/migrate-db.py
Defaults: --source /opt/plansync/plansync.db --dest /opt/data/plansync/plansync.db
"""

import argparse
import json
import os
import sqlite3
import sys
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from plansync.engine import derive_conditions  # noqa: E402

SCHEMA_PATH = os.path.join(REPO_ROOT, "schema.sql")


def canon(cond_type, definition):
    if isinstance(definition, str):
        definition = json.loads(definition)
    return json.dumps({"condition_type": cond_type, "definition": definition}, sort_keys=True)


def fail(dest, msg):
    print(f"error: {msg}", file=sys.stderr)
    for suffix in ("", "-wal", "-shm"):
        p = dest + suffix
        if os.path.exists(p):
            os.remove(p)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="/opt/plansync/plansync.db")
    ap.add_argument("--dest", default="/opt/data/plansync/plansync.db")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        print(f"error: source not found: {args.source}", file=sys.stderr)
        return 1
    if os.path.exists(args.dest):
        print(f"error: dest already exists: {args.dest} -- refusing to overwrite", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.dest), exist_ok=True)

    src = sqlite3.connect(args.source)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(args.dest)
    dst.execute("PRAGMA journal_mode=WAL")
    dst.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        dst.executescript(f.read())

    counts = {}

    # domains: unchanged shape
    for r in src.execute("SELECT * FROM domains"):
        dst.execute(
            "INSERT INTO domains (id,name,location,notes,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (r["id"], r["name"], r["location"], r["notes"], r["created_at"], r["updated_at"]),
        )

    # activities: minus recurrence, deferred -> watching
    remapped = 0
    for r in src.execute("SELECT * FROM activities"):
        status = r["status"]
        if status == "deferred":
            status = "watching"
            remapped += 1
        dst.execute(
            """INSERT INTO activities (id,domain_id,name,description,group_name,status,trigger_type,
               trigger_def,trigger_date,trigger_fired,completed_at,sort_order,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["id"], r["domain_id"], r["name"], r["description"], r["group_name"], status,
             r["trigger_type"], r["trigger_def"], r["trigger_date"], r["trigger_fired"],
             r["completed_at"], r["sort_order"], r["created_at"], r["updated_at"]),
        )

    # steps: minus condition
    for r in src.execute("SELECT * FROM steps"):
        dst.execute(
            """INSERT INTO steps (id,activity_id,name,description,step_type,lead_days,status,
               due_date,completed_at,sort_order,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["id"], r["activity_id"], r["name"], r["description"], r["step_type"], r["lead_days"],
             r["status"], r["due_date"], r["completed_at"], r["sort_order"], r["created_at"], r["updated_at"]),
        )

    # conditions: re-derive from trigger_def, verify parity, carry eval state
    src_cond_count = src.execute("SELECT COUNT(*) FROM conditions").fetchone()[0]
    derived_count = 0
    for act in src.execute("SELECT id, name, trigger_def FROM activities WHERE trigger_def IS NOT NULL"):
        derived = derive_conditions(act["trigger_def"])
        stored = src.execute("SELECT * FROM conditions WHERE activity_id=?", (act["id"],)).fetchall()
        derived_keys = sorted(canon(d["condition_type"], d["definition"]) for d in derived)
        stored_keys = sorted(canon(r["condition_type"], r["definition"]) for r in stored)
        if derived_keys != stored_keys:
            src.close(); dst.close()
            return fail(args.dest,
                        f"conditions parity mismatch for activity '{act['name']}' ({act['id']}):\n"
                        f"  derived: {derived_keys}\n  stored:  {stored_keys}")
        state_by_key = {canon(r["condition_type"], r["definition"]): r for r in stored}
        for d in derived:
            state = state_by_key[canon(d["condition_type"], d["definition"])]
            dst.execute(
                "INSERT INTO conditions (id,activity_id,condition_type,definition,current_value,is_met,last_checked) "
                "VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:12], act["id"], d["condition_type"], json.dumps(d["definition"]),
                 state["current_value"], state["is_met"], state["last_checked"]),
            )
            derived_count += 1

    # weather_log: minus soil_temp, plus weather_date (local day of recorded_at)
    try:
        for r in src.execute(
            "SELECT *, date(recorded_at, 'localtime') as wdate FROM weather_log ORDER BY recorded_at"
        ):
            dst.execute(
                """INSERT INTO weather_log (id,location,weather_date,recorded_at,temp_high,temp_low,
                   conditions,precipitation,forecast_json) VALUES (?,?,?,?,?,?,?,?,?)""",
                (r["id"], r["location"], r["wdate"], r["recorded_at"], r["temp_high"], r["temp_low"],
                 r["conditions"], r["precipitation"], r["forecast_json"]),
            )
    except sqlite3.IntegrityError as e:
        src.close(); dst.close()
        return fail(args.dest,
                    f"duplicate location/day rows in source weather_log ({e}); "
                    "clean them up before migrating")

    # activity_log: unchanged shape (source enum already widened by Step 27)
    for r in src.execute("SELECT * FROM activity_log ORDER BY id"):
        dst.execute(
            "INSERT INTO activity_log (id,timestamp,item_type,item_id,action,old_value,new_value,source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (r["id"], r["timestamp"], r["item_type"], r["item_id"], r["action"],
             r["old_value"], r["new_value"], r["source"]),
        )

    # verify
    for table in ("domains", "activities", "steps", "weather_log", "activity_log"):
        counts[table] = (src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                         dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    counts["conditions"] = (src_cond_count, derived_count)
    mismatched = {t: c for t, c in counts.items() if c[0] != c[1]}
    if mismatched:
        src.close(); dst.close()
        return fail(args.dest, f"row count mismatch: {mismatched}")

    integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
    fk_errors = dst.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or fk_errors:
        src.close(); dst.close()
        return fail(args.dest, f"integrity={integrity}, fk_errors={fk_errors}")

    dst.commit()
    src.close()
    dst.close()

    print(f"migrated {args.source} -> {args.dest}")
    for table, (s, d) in counts.items():
        print(f"  {table}: {s} -> {d}")
    if remapped:
        print(f"  deferred statuses remapped to watching: {remapped}")
    print("  todoist_sync dropped; recurrence/condition/soil_temp columns dropped")
    print("  journal_mode=WAL; UNIQUE(location, weather_date) enforced")
    print(f"source left untouched at {args.source} (rollback path)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
