#!/usr/bin/env python3
"""Step 42: activities without triggers are decided work -- they start
'active', gain trigger machinery only if a trigger_def arrives later."""

import json
import os
import sqlite3

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def call(fn, args):
    import server
    conn = server.get_db()
    try:
        return json.loads(getattr(server, fn)(conn, args).content[0].text)
    finally:
        conn.close()


def add(activities):
    return call("_add_activities", {"domain_id": "d1", "activities": activities})


class TestNoTriggerCreate:
    def test_bare_activity_starts_active(self, db):
        out = add([{"name": "Mulch garlic bed"}])
        assert "error" not in out
        act = out["activities"][0]
        assert act["status"] == "active"
        assert act["trigger_date"] is None
        row = db.execute("SELECT * FROM activities WHERE id=?", (act["id"],)).fetchone()
        assert row["status"] == "active"
        assert row["trigger_type"] is None
        assert row["trigger_def"] is None
        conds = db.execute("SELECT COUNT(*) c FROM conditions WHERE activity_id=?",
                           (act["id"],)).fetchone()["c"]
        assert conds == 0

    def test_no_trigger_steps_get_null_due(self, db):
        out = add([{"name": "Mulch", "steps": [
            {"name": "Buy straw", "step_type": "prep", "lead_days": 3}]}])
        assert "error" not in out
        step = out["activities"][0]["steps"][0]
        assert step["due_date"] is None

    def test_triggered_activity_unchanged(self, db):
        out = add([{"name": "Sow", "trigger_type": "calendar",
                    "trigger_def": {"type": "calendar", "date": "2027-03-01"}}])
        act = out["activities"][0]
        assert act["status"] == "watching"
        assert act["trigger_date"] == "2027-03-01"

    def test_mixed_batch(self, db):
        out = add([
            {"name": "Mulch"},
            {"name": "Sow", "trigger_type": "calendar",
             "trigger_def": {"type": "calendar", "date": "2027-03-01"}},
        ])
        statuses = {a["name"]: a["status"] for a in out["activities"]}
        assert statuses == {"Mulch": "active", "Sow": "watching"}

    def test_load_domain_accepts_no_trigger(self, db):
        out = call("_load_domain", {"definition": {
            "name": "Chores", "location": "X",
            "activities": [{"name": "Clean gutters"}],
        }})
        assert "error" not in out
        assert out["activities"][0]["status"] == "active"


class TestPairValidation:
    def test_trigger_type_without_def_rejected(self, db):
        out = add([{"name": "X", "trigger_type": "calendar"}])
        assert "error" in out
        assert any("trigger_def" in e["path"] for e in out["details"])

    def test_trigger_def_without_type_rejected(self, db):
        out = add([{"name": "X", "trigger_def": {"type": "calendar", "date": "2027-01-01"}}])
        assert "error" in out
        assert any("trigger_type" in e["path"] for e in out["details"])

    def test_invalid_trigger_type_still_rejected(self, db):
        out = add([{"name": "X", "trigger_type": "moonphase",
                    "trigger_def": {"type": "moonphase"}}])
        assert "error" in out

    def test_invalid_metric_still_rejected(self, db):
        out = add([{"name": "X", "trigger_type": "condition",
                    "trigger_def": {"type": "condition",
                                    "all": [{"metric": "soil_temp", "operator": ">=", "value": 55}]}}])
        assert "error" in out


class TestAddTriggerLater:
    def test_update_adds_trigger_and_watches(self, db):
        act = add([{"name": "Mulch", "steps": [
            {"name": "Buy straw", "step_type": "prep", "lead_days": 3}]}])["activities"][0]
        out = call("_update_activity", {
            "activity_id": act["id"],
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2027-03-01"},
        })
        assert "error" not in out
        assert out["status"] == "watching"
        assert out["trigger_date"] == "2027-03-01"
        assert out["steps"][0]["due_date"] == "2027-02-26"

    def test_update_derives_conditions(self, db):
        act = add([{"name": "Watch"}])["activities"][0]
        call("_update_activity", {
            "activity_id": act["id"],
            "trigger_type": "condition",
            "trigger_def": {"type": "condition",
                            "all": [{"metric": "daily_high", "operator": ">=", "value": 85}]},
        })
        conds = db.execute("SELECT COUNT(*) c FROM conditions WHERE activity_id=?",
                           (act["id"],)).fetchone()["c"]
        assert conds == 1
        assert db.execute("SELECT status FROM activities WHERE id=?",
                          (act["id"],)).fetchone()["status"] == "watching"

    def test_changing_existing_trigger_keeps_status(self, db):
        act = add([{"name": "Sow", "trigger_type": "calendar",
                    "trigger_def": {"type": "calendar", "date": "2027-03-01"}}])["activities"][0]
        db.execute("UPDATE activities SET status='preparing' WHERE id=?", (act["id"],))
        db.commit()
        out = call("_update_activity", {
            "activity_id": act["id"],
            "trigger_def": {"type": "calendar", "date": "2027-04-01"},
        })
        assert out["status"] == "preparing"  # not reset by a trigger edit
