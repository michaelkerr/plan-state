#!/usr/bin/env python3
"""Step 43: delete_activity -- soft delete (skip via state machine, undoable)
or permanent (all traces removed)."""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")


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


def seed(db, aid="a1", status="active"):
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def) "
        "VALUES (?,?,?,?,'condition','{\"type\": \"condition\", \"all\": []}')",
        (aid, "d1", aid, status))
    for sid, st in (("p1", "pending"), ("p2", "due"), ("p3", "completed")):
        db.execute(
            "INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
            "VALUES (?,?,?,?,?,'2026-01-01')", (f"{aid}-{sid}", aid, sid, "prep", st))
    db.execute(
        "INSERT INTO conditions (id, activity_id, condition_type, definition) "
        "VALUES (?,?,?,?)", (f"{aid}-c1", aid, "temperature", "{}"))
    db.commit()


def call(fn, args):
    import server
    conn = server.get_db()
    try:
        return json.loads(getattr(server, fn)(conn, args)[0].text)
    finally:
        conn.close()


class TestSoftDelete:
    def test_soft_skips_activity_and_open_steps(self, db):
        seed(db)
        out = call("_delete_activity", {"activity_id": "a1"})
        assert "error" not in out
        assert out["mode"] == "soft"
        assert db.execute("SELECT status FROM activities WHERE id='a1'").fetchone()["status"] == "skipped"
        statuses = {r["id"]: r["status"] for r in db.execute("SELECT id, status FROM steps")}
        assert statuses == {"a1-p1": "skipped", "a1-p2": "skipped", "a1-p3": "completed"}
        assert {s["id"] for s in out["steps_skipped"]} == {"a1-p1", "a1-p2"}

    def test_soft_removes_from_actionable_view(self, db):
        seed(db)
        call("_delete_activity", {"activity_id": "a1"})
        n = db.execute("SELECT COUNT(*) c FROM actionable_items").fetchone()["c"]
        assert n == 0

    def test_soft_shares_one_batch(self, db):
        seed(db)
        out = call("_delete_activity", {"activity_id": "a1"})
        batches = {r["batch_id"] for r in db.execute(
            "SELECT batch_id FROM activity_log WHERE action='status_change'")}
        assert batches == {out["batch_id"]}

    def test_soft_on_completed_rejected(self, db):
        seed(db, status="completed")
        out = call("_delete_activity", {"activity_id": "a1"})
        assert "error" in out
        assert db.execute("SELECT status FROM activities WHERE id='a1'").fetchone()["status"] == "completed"

    def test_missing_activity(self, db):
        out = call("_delete_activity", {"activity_id": "nope"})
        assert "error" in out


class TestPermanentDelete:
    def test_permanent_removes_all_traces(self, db):
        seed(db)
        # produce a log entry tied to a step, too
        from plansync.engine import log_change
        log_change(db, "step", "a1-p1", "manual_update", {}, {})
        log_change(db, "activity", "a1", "manual_update", {}, {})
        db.commit()
        out = call("_delete_activity", {"activity_id": "a1", "permanent": True})
        assert out["mode"] == "permanent"
        assert db.execute("SELECT COUNT(*) c FROM activities").fetchone()["c"] == 0
        assert db.execute("SELECT COUNT(*) c FROM steps").fetchone()["c"] == 0
        assert db.execute("SELECT COUNT(*) c FROM conditions").fetchone()["c"] == 0
        assert db.execute("SELECT COUNT(*) c FROM activity_log").fetchone()["c"] == 0
        assert out["steps_deleted"] == 3
        assert out["conditions_deleted"] == 1

    def test_permanent_leaves_other_activities_alone(self, db):
        seed(db, "a1")
        seed(db, "a2")
        call("_delete_activity", {"activity_id": "a1", "permanent": True})
        remaining = {r["id"] for r in db.execute("SELECT id FROM activities")}
        assert remaining == {"a2"}
        steps = db.execute("SELECT COUNT(*) c FROM steps").fetchone()["c"]
        assert steps == 3

    def test_permanent_works_on_completed(self, db):
        seed(db, status="completed")
        out = call("_delete_activity", {"activity_id": "a1", "permanent": True})
        assert "error" not in out


class TestToolRegistration:
    def test_tool_listed(self):
        import asyncio
        import server
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert "delete_activity" in names
