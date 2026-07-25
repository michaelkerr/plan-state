#!/usr/bin/env python3
"""Step 45: undo -- revert the most recent batch (or the most recent batch
touching a given item), restoring statuses via transition(revert) and field
values from logged old_values."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
MIGRATE_SCRIPT = os.path.join(ROOT, "scripts", "migrate-undo-action.py")
TODAY = date.today()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("PLANSYNC_DB", path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','Garden','X')")
    conn.commit()
    yield conn
    conn.close()


def call(fn, args):
    import server
    conn = server.get_db()
    try:
        return json.loads(getattr(server, fn)(conn, args)[0].text)
    finally:
        conn.close()


def seed_completion_scene(db):
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
        "VALUES ('a1','d1','Main','active','calendar','{\"type\": \"calendar\", \"date\": \"2026-07-01\"}','2026-07-01')")
    db.execute("INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
               "VALUES ('p1','a1','Prep1','prep','due','2026-06-28')")
    db.execute("INSERT INTO steps (id, activity_id, name, step_type, lead_days, status, due_date) "
               "VALUES ('f1','a1','Follow1','follow_up',4,'pending','2026-07-05')")
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
        "VALUES ('dep','d1','Dep','watching','dependency',"
        "'{\"type\": \"dependency\", \"activity_id\": \"a1\", \"event\": \"completed\", \"offset_days\": 3}','2026-08-01')")
    db.commit()


def snapshot(db):
    acts = {r["id"]: (r["status"], r["trigger_date"], r["trigger_fired"])
            for r in db.execute("SELECT * FROM activities")}
    steps = {r["id"]: (r["status"], r["due_date"])
             for r in db.execute("SELECT * FROM steps")}
    return acts, steps


class TestUndoCompletion:
    def test_full_cascade_reverts(self, db):
        seed_completion_scene(db)
        before = snapshot(db)
        out = call("_complete_activity", {"activity_id": "a1"})
        assert "error" not in out
        result = call("_undo", {})
        assert "error" not in result
        assert snapshot(db) == before
        assert result["undo_of"] == out["batch_id"]
        assert len(result["reverted"]) >= 4  # a1, p1, f1, dep

    def test_undo_logged_as_undo_action(self, db):
        seed_completion_scene(db)
        call("_complete_activity", {"activity_id": "a1"})
        call("_undo", {})
        entry = db.execute("SELECT * FROM activity_log WHERE action='undo'").fetchone()
        assert entry is not None
        assert entry["batch_id"] is not None

    def test_undo_an_undo_refused(self, db):
        seed_completion_scene(db)
        call("_complete_activity", {"activity_id": "a1"})
        call("_undo", {})
        out = call("_undo", {})
        assert "error" in out

    def test_nothing_to_undo(self, db):
        out = call("_undo", {})
        assert "error" in out
        assert "othing" in out["error"]  # "Nothing to undo"


class TestUndoTargeted:
    def test_undo_by_item_finds_its_batch(self, db):
        seed_completion_scene(db)
        db.execute("INSERT INTO activities (id, domain_id, name, status) "
                   "VALUES ('other','d1','Other','active')")
        db.commit()
        call("_complete_activity", {"activity_id": "a1"})
        call("_complete_activity", {"activity_id": "other"})  # most recent batch
        result = call("_undo", {"item_type": "activity", "item_id": "a1"})
        assert "error" not in result
        assert db.execute("SELECT status FROM activities WHERE id='a1'").fetchone()["status"] == "active"
        # the other completion is untouched
        assert db.execute("SELECT status FROM activities WHERE id='other'").fetchone()["status"] == "completed"


class TestUndoOtherOperations:
    def test_undo_step_completion(self, db):
        seed_completion_scene(db)
        call("_update_step", {"step_id": "p1", "status": "completed"})
        result = call("_undo", {})
        assert "error" not in result
        row = db.execute("SELECT status, completed_at FROM steps WHERE id='p1'").fetchone()
        assert row["status"] == "due"
        assert row["completed_at"] is None

    def test_undo_deferral(self, db):
        seed_completion_scene(db)
        before = snapshot(db)
        before_tdef = db.execute("SELECT trigger_def FROM activities WHERE id='a1'").fetchone()["trigger_def"]
        call("_defer_activity", {"activity_id": "a1", "new_date": "2026-09-01", "reason": "r"})
        result = call("_undo", {})
        assert "error" not in result
        assert snapshot(db) == before
        after_tdef = db.execute("SELECT trigger_def FROM activities WHERE id='a1'").fetchone()["trigger_def"]
        assert json.loads(after_tdef) == json.loads(before_tdef)

    def test_undo_soft_delete(self, db):
        seed_completion_scene(db)
        before = snapshot(db)
        call("_delete_activity", {"activity_id": "a1"})
        result = call("_undo", {})
        assert "error" not in result
        assert snapshot(db) == before

    def test_undo_cron_trigger_fire(self, db):
        sys.path.insert(0, os.path.join(ROOT, "sync"))
        import sync_pipeline
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
            "VALUES ('a9','d1','Fire','watching','calendar',?,?)",
            (json.dumps({"type": "calendar", "date": yesterday}), yesterday))
        db.commit()
        sync_pipeline.evaluate_triggers(db, sync_pipeline.SyncSummary())
        db.commit()
        assert db.execute("SELECT status FROM activities WHERE id='a9'").fetchone()["status"] == "active"
        result = call("_undo", {})
        assert "error" not in result
        row = db.execute("SELECT status, trigger_fired, trigger_date FROM activities WHERE id='a9'").fetchone()
        assert row["status"] == "watching"
        assert row["trigger_fired"] is None
        assert row["trigger_date"] == yesterday


class TestSchemaAndMigration:
    def test_new_schema_accepts_undo_action(self, db):
        db.execute(
            "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source) "
            "VALUES ('activity','x','undo',NULL,'{}','claude')")
        db.commit()

    def test_migration_widens_live_check(self, tmp_path):
        path = str(tmp_path / "live.db")
        conn = sqlite3.connect(path)
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        # Rebuild activity_log with the pre-45 CHECK (no 'undo')
        conn.executescript("""
            DROP TABLE activity_log;
            CREATE TABLE activity_log (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
              item_type       TEXT NOT NULL CHECK(item_type IN ('domain','activity','step','condition')),
              item_id         TEXT NOT NULL,
              action          TEXT NOT NULL CHECK(action IN ('status_change','date_cascade','trigger_fire','manual_update','created','observation')),
              old_value       JSON,
              new_value       JSON,
              source          TEXT NOT NULL CHECK(source IN ('cron','hermes','claude','human')),
              batch_id        TEXT
            );
        """)
        conn.execute(
            "INSERT INTO activity_log (item_type, item_id, action, source) "
            "VALUES ('activity','x','created','hermes')")
        conn.commit()
        conn.close()
        for _ in range(2):  # idempotent
            r = subprocess.run([sys.executable, MIGRATE_SCRIPT],
                               env={**os.environ, "PLANSYNC_DB": path},
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO activity_log (item_type, item_id, action, source) "
            "VALUES ('activity','y','undo','claude')")
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 2
        conn.close()

    def test_tool_listed(self):
        import asyncio
        import server
        names = {t.name for t in asyncio.run(server.list_tools())}
        assert "undo" in names
