#!/usr/bin/env python3
"""Step 37: sync_pipeline trigger fires and overdue promotion route through
engine.transition() -- same state machine as the MCP server."""

import json
import os
import sqlite3
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


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


def add_activity(db, aid, status="watching", trigger_def=None, trigger_date=None):
    tdef = trigger_def or {"type": "calendar", "date": trigger_date or YESTERDAY}
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
        "VALUES (?,?,?,?,?,?,?)",
        (aid, "d1", aid, status, tdef["type"], json.dumps(tdef), trigger_date),
    )
    db.commit()


def add_step(db, sid, aid, step_type="prep", status="pending", lead_days=0, due_date=None):
    db.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, lead_days, status, due_date) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, aid, sid, step_type, lead_days, status, due_date),
    )
    db.commit()


def status_of(db, table, eid):
    return db.execute(f"SELECT status FROM {table} WHERE id=?", (eid,)).fetchone()["status"]


class TestTriggerFireViaTransition:
    def test_fire_without_prep_goes_active(self, db):
        import sync_pipeline
        add_activity(db, "a1", trigger_date=YESTERDAY)
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.evaluate_triggers(db, summary)
        db.commit()
        a = db.execute("SELECT * FROM activities WHERE id='a1'").fetchone()
        assert a["status"] == "active"
        assert a["trigger_fired"] is not None
        assert [t["name"] for t in summary.triggers_fired] == ["a1"]

    def test_fire_with_prep_goes_preparing_and_cascades(self, db):
        import sync_pipeline
        add_activity(db, "a1", trigger_date=YESTERDAY)
        add_step(db, "p1", "a1", step_type="prep", lead_days=2)
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.evaluate_triggers(db, summary)
        db.commit()
        assert status_of(db, "activities", "a1") == "preparing"
        p1 = db.execute("SELECT due_date FROM steps WHERE id='p1'").fetchone()
        assert p1["due_date"] == (date.fromisoformat(YESTERDAY) - timedelta(days=2)).isoformat()

    def test_fire_logs_trigger_fire_with_cron_source_and_batch(self, db):
        import sync_pipeline
        add_activity(db, "a1", trigger_date=YESTERDAY)
        add_step(db, "p1", "a1", step_type="prep", lead_days=2)
        sync_pipeline.evaluate_triggers(db, sync_pipeline.SyncSummary())
        db.commit()
        entries = db.execute("SELECT * FROM activity_log ORDER BY id").fetchall()
        fire = [e for e in entries if e["action"] == "trigger_fire"]
        assert len(fire) == 1
        assert fire[0]["source"] == "cron"
        assert fire[0]["batch_id"] is not None
        assert json.loads(fire[0]["new_value"])["reason"].startswith("calendar")
        # the step-date cascade shares the fire's batch
        cascade = [e for e in entries if e["action"] == "date_cascade"]
        assert cascade and all(e["batch_id"] == fire[0]["batch_id"] for e in cascade)

    def test_two_fires_get_distinct_batches(self, db):
        import sync_pipeline
        add_activity(db, "a1", trigger_date=YESTERDAY)
        add_activity(db, "a2", trigger_date=YESTERDAY)
        sync_pipeline.evaluate_triggers(db, sync_pipeline.SyncSummary())
        db.commit()
        batches = {r["batch_id"] for r in db.execute(
            "SELECT batch_id FROM activity_log WHERE action='trigger_fire'")}
        assert len(batches) == 2

    def test_unfired_trigger_untouched(self, db):
        import sync_pipeline
        future = (TODAY + timedelta(days=30)).isoformat()
        add_activity(db, "a1", trigger_date=future)
        sync_pipeline.evaluate_triggers(db, sync_pipeline.SyncSummary())
        db.commit()
        assert status_of(db, "activities", "a1") == "watching"


class TestOverdueViaTransition:
    def test_pending_past_due_promotes(self, db):
        import sync_pipeline
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="pending", due_date=YESTERDAY)
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.check_overdue(db, summary)
        db.commit()
        assert status_of(db, "steps", "s1") == "due"
        assert len(summary.overdue) == 1

    def test_already_due_reported_not_retransitioned(self, db):
        import sync_pipeline
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="due", due_date=YESTERDAY)
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.check_overdue(db, summary)
        db.commit()
        assert status_of(db, "steps", "s1") == "due"
        assert len(summary.overdue) == 1
        # no status_change logged -- it was already 'due'
        n = db.execute("SELECT COUNT(*) c FROM activity_log WHERE action='status_change'").fetchone()["c"]
        assert n == 0

    def test_promotion_logged_with_cron_source(self, db):
        import sync_pipeline
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="pending", due_date=YESTERDAY)
        sync_pipeline.check_overdue(db, sync_pipeline.SyncSummary())
        db.commit()
        entry = db.execute(
            "SELECT * FROM activity_log WHERE item_type='step' AND item_id='s1'").fetchone()
        assert entry is not None
        assert entry["action"] == "status_change"
        assert entry["source"] == "cron"
        assert entry["batch_id"] is not None
        assert json.loads(entry["new_value"])["status"] == "due"

    def test_future_and_closed_steps_untouched(self, db):
        import sync_pipeline
        add_activity(db, "a1", status="active")
        add_activity(db, "a2", status="completed")
        tomorrow = (TODAY + timedelta(days=1)).isoformat()
        add_step(db, "s1", "a1", status="pending", due_date=tomorrow)
        add_step(db, "s2", "a2", status="pending", due_date=YESTERDAY)  # parent completed
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.check_overdue(db, summary)
        db.commit()
        assert status_of(db, "steps", "s1") == "pending"
        assert status_of(db, "steps", "s2") == "pending"
        assert summary.overdue == []


class TestNoRawStatusUpdates:
    def test_sync_functions_have_no_raw_status_updates(self):
        import inspect
        import sync_pipeline
        for fn in ("evaluate_triggers", "check_overdue"):
            src = inspect.getsource(getattr(sync_pipeline, fn))
            assert "SET status" not in src, f"{fn} still writes status directly"
