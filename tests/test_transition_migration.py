#!/usr/bin/env python3
"""Step 36: server.py status changes route through engine.transition()/react().

Locks in the two v1 bug fixes: prep steps in 'due' auto-complete on activity
completion, and invalid transitions are rejected instead of silently applied.
"""

import inspect
import json
import os
import sqlite3
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
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
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','Test','X')")
    conn.commit()
    yield conn
    conn.close()


def add_activity(db, aid, status="watching", trigger_type="calendar",
                 trigger_def=None, trigger_date=None):
    tdef = json.dumps(trigger_def if trigger_def else
                      {"type": "calendar", "date": trigger_date or "2027-01-01"})
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
        "VALUES (?,?,?,?,?,?,?)",
        (aid, "d1", aid, status, trigger_type, tdef, trigger_date),
    )
    db.commit()


def add_step(db, sid, aid, step_type="prep", status="pending", lead_days=0, due_date=None):
    db.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, lead_days, status, due_date) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, aid, sid, step_type, lead_days, status, due_date),
    )
    db.commit()


def call(fn, args):
    import server
    conn = server.get_db()
    try:
        return json.loads(getattr(server, fn)(conn, args)[0].text)
    finally:
        conn.close()


def status_of(db, table, eid):
    return db.execute(f"SELECT status FROM {table} WHERE id=?", (eid,)).fetchone()["status"]


class TestCompleteActivity:
    def test_due_prep_steps_auto_complete(self, db):
        # The v1 bug: only status='pending' prep steps were auto-completed
        add_activity(db, "a1", status="active")
        add_step(db, "p1", "a1", step_type="prep", status="due")
        add_step(db, "p2", "a1", step_type="prep", status="pending")
        out = call("_complete_activity", {"activity_id": "a1"})
        assert "error" not in out
        assert status_of(db, "steps", "p1") == "completed"
        assert status_of(db, "steps", "p2") == "completed"

    def test_follow_ups_promoted_with_batch(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "f1", "a1", step_type="follow_up", status="pending", lead_days=4)
        out = call("_complete_activity", {"activity_id": "a1"})
        assert out["follow_up_steps_due"][0]["id"] == "f1"
        assert out["follow_up_steps_due"][0]["due_date"] == (TODAY + timedelta(days=4)).isoformat()
        assert status_of(db, "steps", "f1") == "due"
        batches = {r["batch_id"] for r in db.execute(
            "SELECT batch_id FROM activity_log WHERE item_id IN ('a1','f1')")}
        assert len(batches) == 1 and None not in batches

    def test_dependency_fires(self, db):
        add_activity(db, "a1", status="active")
        add_activity(db, "dep", status="watching", trigger_type="dependency",
                     trigger_def={"type": "dependency", "activity_id": "a1",
                                  "event": "completed", "offset_days": 2})
        out = call("_complete_activity", {"activity_id": "a1"})
        fired = out["dependent_activities_activated"]
        assert fired[0]["id"] == "dep"
        assert fired[0]["trigger_date"] == (TODAY + timedelta(days=2)).isoformat()
        # no prep steps -> fires straight to active under the unified rule
        assert status_of(db, "activities", "dep") == "active"

    def test_complete_watching_rejected(self, db):
        add_activity(db, "a1", status="watching")
        out = call("_complete_activity", {"activity_id": "a1"})
        assert "error" in out
        assert "watching" in out["error"]
        assert status_of(db, "activities", "a1") == "watching"

    def test_complete_twice_rejected(self, db):
        add_activity(db, "a1", status="active")
        assert "error" not in call("_complete_activity", {"activity_id": "a1"})
        out = call("_complete_activity", {"activity_id": "a1"})
        assert "error" in out

    def test_notes_logged(self, db):
        add_activity(db, "a1", status="active")
        call("_complete_activity", {"activity_id": "a1", "notes": "went great"})
        entry = db.execute(
            "SELECT new_value FROM activity_log WHERE item_id='a1' AND action='status_change'"
        ).fetchone()
        assert json.loads(entry["new_value"])["notes"] == "went great"

    def test_response_shape_preserved(self, db):
        add_activity(db, "a1", status="active")
        out = call("_complete_activity", {"activity_id": "a1"})
        assert out["completed"] == "a1"
        assert "follow_up_steps_due" in out
        assert "dependent_activities_activated" in out


class TestDeferActivity:
    def test_defer_batches_all_entries(self, db):
        add_activity(db, "a1", status="preparing", trigger_date="2027-01-01")
        add_step(db, "p1", "a1", step_type="prep", lead_days=3, due_date="2026-12-29")
        out = call("_defer_activity", {"activity_id": "a1", "new_date": "2027-06-01", "reason": "r"})
        assert "error" not in out
        assert status_of(db, "activities", "a1") == "watching"
        rows = db.execute("SELECT batch_id FROM activity_log").fetchall()
        batches = {r["batch_id"] for r in rows}
        assert len(rows) >= 2  # status_change + date move (+ step cascade)
        assert len(batches) == 1 and None not in batches

    def test_defer_completed_rejected(self, db):
        add_activity(db, "a1", status="completed")
        out = call("_defer_activity", {"activity_id": "a1", "new_date": "2027-06-01"})
        assert "error" in out
        assert status_of(db, "activities", "a1") == "completed"


class TestUpdateStepStatus:
    def test_due_step_completes(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="due")
        out = call("_update_step", {"step_id": "s1", "status": "completed"})
        assert out["status"] == "completed"
        assert out["completed_at"] is not None

    def test_invalid_status_move_rejected(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="due")
        out = call("_update_step", {"step_id": "s1", "status": "pending"})
        assert "error" in out
        assert status_of(db, "steps", "s1") == "due"

    def test_skipped_step_recoverable(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="skipped")
        out = call("_update_step", {"step_id": "s1", "status": "pending"})
        assert out["status"] == "pending"

    def test_fields_and_status_together(self, db):
        add_activity(db, "a1", status="active", trigger_date="2099-06-01")
        add_step(db, "s1", "a1", step_type="prep", status="pending", lead_days=5)
        out = call("_update_step", {"step_id": "s1", "name": "Renamed", "status": "completed"})
        assert out["name"] == "Renamed"
        assert out["status"] == "completed"


class TestNoRawStatusUpdates:
    def test_migrated_functions_have_no_raw_status_updates(self):
        import server
        for fn in ("_complete_activity", "_defer_activity", "_update_step"):
            src = inspect.getsource(getattr(server, fn))
            # Literal raw-SQL status writes (the behavioral tests above prove
            # the transition table is actually consulted -- a raw UPDATE would
            # not reject invalid moves)
            assert "SET status" not in src, f"{fn} still writes status directly"
            assert "status='" not in src, f"{fn} still writes status directly"
