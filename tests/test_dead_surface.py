#!/usr/bin/env python3
"""Step 23: dead/trap surface removed -- schema, tools, and skills describe
only behavior that actually executes."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, os.path.join(ROOT, "sync"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")

DOMAIN = {
    "name": "Dead Surface Test",
    "location": "Murfreesboro,TN,US",
    "activities": [
        {
            "name": "Calendar Act",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2099-06-01"},
            "steps": [
                {"name": "Prep step", "step_type": "prep", "lead_days": 5},
                {"name": "Follow step", "step_type": "follow_up", "lead_days": 2},
            ],
        },
        {
            "name": "Second Act",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2099-07-01"},
            "steps": [{"name": "Other prep", "step_type": "prep", "lead_days": 3}],
        },
    ],
}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("PLANSYNC_DB", path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.close()
    return path


@pytest.fixture
def db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def call(fn, *args):
    import server
    conn = server.get_db()
    try:
        result = getattr(server, fn)(conn, *args)
        return json.loads(result[0].text)
    finally:
        conn.close()


def load(definition=DOMAIN):
    return call("_load_domain", {"definition": definition})


class TestDeferFix:
    def test_defer_keeps_watching_and_moves_date(self, db):
        result = load()
        act = result["activities"][0]
        out = call("_defer_activity", {"activity_id": act["id"], "new_date": "2099-08-01", "reason": "too wet"})
        assert "error" not in out
        row = db.execute("SELECT status, trigger_date FROM activities WHERE id=?", (act["id"],)).fetchone()
        assert row["status"] == "watching"
        assert row["trigger_date"] == "2099-08-01"

    def test_defer_cascades_steps(self, db):
        result = load()
        act = result["activities"][0]
        call("_defer_activity", {"activity_id": act["id"], "new_date": "2099-08-01", "reason": "r"})
        dues = {r["name"]: r["due_date"] for r in db.execute(
            "SELECT name, due_date FROM steps WHERE activity_id=?", (act["id"],))}
        assert dues == {"Prep step": "2099-07-27", "Follow step": "2099-08-03"}

    def test_defer_requires_new_date(self, db):
        result = load()
        act = result["activities"][0]
        out = call("_defer_activity", {"activity_id": act["id"], "reason": "r"})
        assert "error" in out

    def test_deferred_activity_fires_on_new_date(self, db):
        import sync_pipeline
        result = load()
        act = result["activities"][0]
        # defer to a date already past -> next trigger evaluation fires it
        call("_defer_activity", {"activity_id": act["id"], "new_date": "2020-01-15", "reason": "r"})
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.evaluate_triggers(db, summary)
        db.commit()
        assert "Calendar Act" in {t["name"] for t in summary.triggers_fired}
        assert db.execute("SELECT status FROM activities WHERE id=?", (act["id"],)).fetchone()["status"] == "preparing"

    def test_defer_resets_fired_activity_to_watching(self, db):
        result = load()
        act = result["activities"][0]
        db.execute("UPDATE activities SET status='preparing', trigger_fired='2026-01-01T06:00:00' WHERE id=?", (act["id"],))
        db.commit()
        call("_defer_activity", {"activity_id": act["id"], "new_date": "2099-09-01", "reason": "r"})
        row = db.execute("SELECT status, trigger_fired FROM activities WHERE id=?", (act["id"],)).fetchone()
        assert row["status"] == "watching"
        assert row["trigger_fired"] is None

    def test_defer_trigger_def_rewrites(self):
        from plansync.engine import defer_trigger_def
        assert defer_trigger_def({"type": "calendar", "date": "2026-09-05"}, "2026-10-01") == {
            "type": "calendar", "date": "2026-10-01"}
        compound = {
            "type": "compound", "operator": "AND",
            "conditions": [
                {"type": "calendar", "after": "2026-09-05"},
                {"type": "condition", "all": [{"metric": "daily_high", "operator": "<=", "value": 85}]},
            ],
        }
        moved = defer_trigger_def(compound, "2026-10-01")
        assert moved["conditions"][0] == {"type": "calendar", "after": "2026-10-01"}
        assert moved["conditions"][1] == compound["conditions"][1]
        cond = {"type": "condition", "all": [{"metric": "daily_low", "operator": ">=", "value": 68}]}
        wrapped = defer_trigger_def(cond, "2026-10-01")
        assert wrapped["type"] == "compound"
        assert wrapped["conditions"][0] == {"type": "calendar", "after": "2026-10-01"}
        assert wrapped["conditions"][1] == cond

    def test_deferred_status_dropped_from_enum(self, db):
        result = load()
        act = result["activities"][0]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE activities SET status='deferred' WHERE id=?", (act["id"],))


class TestOverdueParentFilter:
    def _make_overdue_step(self, db, activity_id):
        db.execute(
            "UPDATE steps SET due_date='2020-01-01', status='pending' WHERE activity_id=?",
            (activity_id,),
        )
        db.commit()

    @pytest.mark.parametrize("parent_status,expected", [
        ("watching", True), ("preparing", True), ("active", True),
        ("completed", False), ("skipped", False),
    ])
    def test_overdue_respects_parent_status(self, db, parent_status, expected):
        import sync_pipeline
        result = load()
        act = result["activities"][0]
        self._make_overdue_step(db, act["id"])
        db.execute("UPDATE activities SET status=? WHERE id=?", (parent_status, act["id"]))
        db.commit()
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.check_overdue(db, summary)
        names = {o["name"] for o in summary.overdue}
        assert any("Calendar Act" in n for n in names) == expected


class TestDeadFieldsRejected:
    def test_soil_temp_metric_rejected(self, db):
        bad = json.loads(json.dumps(DOMAIN))
        bad["activities"][0]["trigger_type"] = "condition"
        bad["activities"][0]["trigger_def"] = {
            "type": "condition",
            "all": [{"metric": "soil_temp", "operator": ">=", "value": 55, "sustained_days": 3}],
        }
        result = load(bad)
        assert result["error"] == "Validation failed"
        err = next(e for e in result["details"] if "soil_temp" in e["error"])
        assert "daily_high" in err["error"]

    def test_unknown_metric_rejected(self, db):
        bad = json.loads(json.dumps(DOMAIN))
        bad["activities"][0]["trigger_type"] = "condition"
        bad["activities"][0]["trigger_def"] = {
            "type": "condition",
            "all": [{"metric": "humidity", "operator": ">=", "value": 55}],
        }
        result = load(bad)
        assert result["error"] == "Validation failed"

    def test_recurrence_field_rejected(self, db):
        bad = json.loads(json.dumps(DOMAIN))
        bad["activities"][0]["recurrence"] = {"type": "annual", "month": 9, "day": 1}
        result = load(bad)
        assert result["error"] == "Validation failed"
        assert any("recurrence" in e["path"] for e in result["details"])

    def test_step_condition_field_rejected(self, db):
        bad = json.loads(json.dumps(DOMAIN))
        bad["activities"][0]["steps"][0]["condition"] = {"metric": "daily_high"}
        result = load(bad)
        assert result["error"] == "Validation failed"
        assert any("condition" in e["path"] for e in result["details"])

    def test_dead_columns_gone_from_schema(self, db):
        act_cols = {r["name"] for r in db.execute("PRAGMA table_info(activities)")}
        step_cols = {r["name"] for r in db.execute("PRAGMA table_info(steps)")}
        weather_cols = {r["name"] for r in db.execute("PRAGMA table_info(weather_log)")}
        assert "recurrence" not in act_cols
        assert "condition" not in step_cols
        assert "soil_temp" not in weather_cols


class TestObservationsSurface:
    def test_observation_appears_in_briefing_context(self, db, db_path, tmp_path):
        result = load()
        call("_add_observation", {
            "domain_id": result["id"],
            "observation_text": "Armyworms spotted near the back fence",
        })
        env = dict(os.environ)
        env["PLANSYNC_DB"] = db_path
        env["PLANSYNC_OUTPUT_DIR"] = str(tmp_path / "sync-output")
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, "sync", "briefing_context.py")],
            capture_output=True, text=True, env=env,
        )
        assert out.returncode == 0, out.stderr
        assert "Recent Observations" in out.stdout
        assert "Armyworms spotted near the back fence" in out.stdout

    def test_old_observation_not_in_briefing(self, db, db_path, tmp_path):
        result = load()
        call("_add_observation", {"domain_id": result["id"], "observation_text": "Ancient note"})
        db.execute("UPDATE activity_log SET timestamp=datetime('now', '-10 days') WHERE action='observation'")
        db.commit()
        env = dict(os.environ)
        env["PLANSYNC_DB"] = db_path
        env["PLANSYNC_OUTPUT_DIR"] = str(tmp_path / "sync-output")
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, "sync", "briefing_context.py")],
            capture_output=True, text=True, env=env,
        )
        assert "Ancient note" not in out.stdout
