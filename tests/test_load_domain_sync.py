#!/usr/bin/env python3
"""Step 47: load_domain sync mode -- re-loading an existing domain diffs the
declaration against DB state instead of rejecting."""

import copy
import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")

DOMAIN = {
    "name": "Sync Test",
    "location": "X",
    "activities": [
        {
            "name": "Sow Broccoli",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2099-06-01"},
            "steps": [
                {"name": "Rake bed", "step_type": "prep", "lead_days": 5},
                {"name": "Water in", "step_type": "follow_up", "lead_days": 2},
            ],
        },
        {"name": "Mulch Paths"},
    ],
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("PLANSYNC_DB", path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    yield conn
    conn.close()


def call(args):
    import server
    conn = server.get_db()
    try:
        return json.loads(server._load_domain(conn, args)[0].text)
    finally:
        conn.close()


@pytest.fixture
def loaded(db):
    out = call({"definition": DOMAIN})
    assert "error" not in out
    return out


class TestSyncDiff:
    def test_reload_unchanged_is_empty_diff(self, db, loaded):
        out = call({"definition": DOMAIN})
        assert out["mode"] == "sync"
        assert out["applied"] is True
        assert out["created"] == []
        assert out["updated"] == []
        assert out["flagged_missing"] == []
        assert out["steps_created"] == [] and out["steps_updated"] == [] and out["steps_flagged"] == []

    def test_new_activity_created(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"].append({"name": "Net Berries"})
        out = call({"definition": d})
        assert [c["name"] for c in out["created"]] == ["Net Berries"]
        n = db.execute("SELECT COUNT(*) c FROM activities").fetchone()["c"]
        assert n == 3

    def test_rename_matched_by_ref_name(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"][0]["name"] = "Sow Cabbage"
        d["activities"][0]["ref_name"] = "sow-broccoli"
        out = call({"definition": d})
        assert out["created"] == []
        assert len(out["updated"]) == 1
        assert out["updated"][0]["changes"]["name"]["new"] == "Sow Cabbage"
        row = db.execute("SELECT name, ref_name FROM activities WHERE ref_name='sow-broccoli'").fetchone()
        assert row["name"] == "Sow Cabbage"

    def test_trigger_def_change_applied_and_cascaded(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"][0]["trigger_def"] = {"type": "calendar", "date": "2099-07-01"}
        out = call({"definition": d})
        assert len(out["updated"]) == 1
        act = db.execute("SELECT * FROM activities WHERE ref_name='sow-broccoli'").fetchone()
        assert act["trigger_date"] == "2099-07-01"
        due = db.execute("SELECT due_date FROM steps WHERE name='Rake bed'").fetchone()["due_date"]
        assert due == "2099-06-26"

    def test_removed_activity_flagged_not_deleted(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"] = [d["activities"][0]]
        out = call({"definition": d})
        assert [f["name"] for f in out["flagged_missing"]] == ["Mulch Paths"]
        n = db.execute("SELECT COUNT(*) c FROM activities").fetchone()["c"]
        assert n == 2  # nothing deleted

    def test_dry_run_reports_without_applying(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"].append({"name": "Net Berries"})
        d["activities"][0]["trigger_def"] = {"type": "calendar", "date": "2099-07-01"}
        out = call({"definition": d, "dry_run": True})
        assert out["dry_run"] is True and out["applied"] is False
        assert [c["name"] for c in out["created"]] == ["Net Berries"]
        assert len(out["updated"]) == 1
        assert db.execute("SELECT COUNT(*) c FROM activities").fetchone()["c"] == 2
        assert db.execute("SELECT trigger_date FROM activities WHERE ref_name='sow-broccoli'").fetchone()["trigger_date"] == "2099-06-01"


class TestStepSync:
    def test_step_added(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"][0]["steps"].append({"name": "Thin seedlings", "step_type": "follow_up", "lead_days": 10})
        out = call({"definition": d})
        assert [s["name"] for s in out["steps_created"]] == ["Thin seedlings"]
        due = db.execute("SELECT due_date FROM steps WHERE name='Thin seedlings'").fetchone()["due_date"]
        assert due == "2099-06-11"

    def test_step_changed(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"][0]["steps"][0]["lead_days"] = 8
        out = call({"definition": d})
        assert len(out["steps_updated"]) == 1
        row = db.execute("SELECT lead_days, due_date FROM steps WHERE name='Rake bed'").fetchone()
        assert row["lead_days"] == 8
        assert row["due_date"] == "2099-05-24"

    def test_step_missing_flagged_not_deleted(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"][0]["steps"] = [d["activities"][0]["steps"][0]]
        out = call({"definition": d})
        assert [s["name"] for s in out["steps_flagged"]] == ["Water in"]
        assert db.execute("SELECT COUNT(*) c FROM steps").fetchone()["c"] == 2


class TestTriggerGain:
    def test_decided_work_gains_trigger_goes_watching(self, db, loaded):
        d = copy.deepcopy(DOMAIN)
        d["activities"][1]["trigger_type"] = "calendar"
        d["activities"][1]["trigger_def"] = {"type": "calendar", "date": "2099-09-01"}
        out = call({"definition": d})
        assert len(out["updated"]) == 1
        row = db.execute("SELECT status, trigger_date FROM activities WHERE ref_name='mulch-paths'").fetchone()
        assert row["status"] == "watching"
        assert row["trigger_date"] == "2099-09-01"

    def test_omitted_trigger_left_alone(self, db, loaded):
        # declaration without trigger fields does NOT strip an existing trigger
        d = copy.deepcopy(DOMAIN)
        del d["activities"][0]["trigger_type"]
        del d["activities"][0]["trigger_def"]
        out = call({"definition": d})
        assert out["updated"] == []
        row = db.execute("SELECT trigger_type FROM activities WHERE ref_name='sow-broccoli'").fetchone()
        assert row["trigger_type"] == "calendar"
