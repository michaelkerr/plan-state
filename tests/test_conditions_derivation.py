#!/usr/bin/env python3
"""Step 22: conditions derived from trigger_def; create_domain/create_activity retired."""

import asyncio
import json
import os
import sqlite3

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")

DOMAIN = {
    "name": "Derivation Test",
    "location": "Murfreesboro,TN,US",
    "activities": [
        {
            "name": "Condition Act",
            "trigger_type": "condition",
            "trigger_def": {
                "type": "condition",
                "all": [{"metric": "daily_low", "operator": ">=", "value": 68, "sustained_days": 3}],
            },
        },
        {
            "name": "Compound Act",
            "trigger_type": "compound",
            "trigger_def": {
                "type": "compound",
                "operator": "AND",
                "conditions": [
                    {"type": "calendar", "after": "2020-01-05"},
                    {"type": "condition", "all": [
                        {"metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 2},
                        {"metric": "daily_low", "operator": ">=", "value": 40, "sustained_days": 1},
                    ]},
                ],
            },
            "steps": [{"name": "Prep", "step_type": "prep", "lead_days": 2}],
        },
        {
            "name": "Calendar Act",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2099-04-01"},
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
        return json.loads(result.content[0].text)
    finally:
        conn.close()


def load(definition):
    return call("_load_domain", {"definition": definition})


def conditions_for(db, name):
    return [
        dict(r) for r in db.execute(
            "SELECT c.* FROM conditions c JOIN activities a ON c.activity_id=a.id WHERE a.name=?",
            (name,),
        ).fetchall()
    ]


class TestDerivation:
    def test_condition_activity_derives_row(self, db):
        result = load(DOMAIN)
        assert "error" not in result
        rows = conditions_for(db, "Condition Act")
        assert len(rows) == 1
        assert rows[0]["condition_type"] == "temperature"
        assert json.loads(rows[0]["definition"]) == {
            "metric": "daily_low", "operator": ">=", "value": 68, "sustained_days": 3}

    def test_compound_activity_derives_leaf_clauses(self, db):
        load(DOMAIN)
        rows = conditions_for(db, "Compound Act")
        defs = sorted((json.loads(r["definition"])["metric"] for r in rows))
        assert defs == ["daily_high", "daily_low"]
        assert all(r["condition_type"] == "temperature" for r in rows)

    def test_calendar_activity_derives_nothing(self, db):
        load(DOMAIN)
        assert conditions_for(db, "Calendar Act") == []

    def test_explicit_conditions_array_rejected_with_rollback(self, db):
        bad = json.loads(json.dumps(DOMAIN))
        bad["activities"][0]["conditions"] = [
            {"condition_type": "temperature",
             "definition": {"metric": "daily_low", "operator": ">=", "value": 68}},
        ]
        result = load(bad)
        assert result["error"] == "Validation failed"
        assert any("conditions" in e["path"] and "derived" in e["error"] for e in result["details"])
        assert db.execute("SELECT COUNT(*) FROM domains").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0

    def test_add_activities_rejects_conditions_array(self, db):
        result = load(DOMAIN)
        bad_batch = [{
            "name": "New Act",
            "trigger_type": "condition",
            "trigger_def": {"type": "condition", "all": [{"metric": "daily_high", "operator": "<=", "value": 90}]},
            "conditions": [{"condition_type": "temperature", "definition": {"metric": "daily_high", "operator": "<=", "value": 90}}],
        }]
        out = call("_add_activities", {"domain_id": result["id"], "activities": bad_batch})
        assert out["error"] == "Validation failed"
        assert db.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 3

    def test_add_activities_derives(self, db):
        result = load(DOMAIN)
        batch = [{
            "name": "New Act",
            "trigger_type": "condition",
            "trigger_def": {"type": "condition", "all": [{"metric": "daily_high", "operator": "<=", "value": 90, "sustained_days": 2}]},
        }]
        out = call("_add_activities", {"domain_id": result["id"], "activities": batch})
        assert "error" not in out
        rows = conditions_for(db, "New Act")
        assert len(rows) == 1
        assert json.loads(rows[0]["definition"])["value"] == 90


class TestUpdateRederivation:
    def test_update_trigger_def_rederives(self, db):
        result = load(DOMAIN)
        act = next(a for a in result["activities"] if a["name"] == "Condition Act")
        out = call("_update_activity", {
            "activity_id": act["id"],
            "trigger_def": {"type": "condition", "all": [
                {"metric": "daily_high", "operator": "<=", "value": 55, "sustained_days": 2}]},
        })
        assert "error" not in out
        rows = conditions_for(db, "Condition Act")
        assert len(rows) == 1
        assert json.loads(rows[0]["definition"]) == {
            "metric": "daily_high", "operator": "<=", "value": 55, "sustained_days": 2}

    def test_update_without_trigger_def_keeps_conditions(self, db):
        result = load(DOMAIN)
        act = next(a for a in result["activities"] if a["name"] == "Condition Act")
        before = conditions_for(db, "Condition Act")
        call("_update_activity", {"activity_id": act["id"], "description": "renamed"})
        assert conditions_for(db, "Condition Act") == before


class TestEndToEndFiring:
    def test_derived_conditions_fire_trigger(self, db):
        """Seed qualifying weather, run the cron eval steps, compound fires."""
        import sync_pipeline
        load(DOMAIN)
        for day_offset in (2, 1, 0):
            db.execute(
                "INSERT INTO weather_log (location, weather_date, temp_high, temp_low, recorded_at) "
                "VALUES ('Murfreesboro,TN,US', date('now', ?), 80, 65, datetime('now', ?))",
                (f"-{day_offset} days", f"-{day_offset} days"),
            )
        db.commit()
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.evaluate_conditions(db, summary)
        db.commit()
        sync_pipeline.evaluate_triggers(db, summary)
        db.commit()
        fired = {t["name"] for t in summary.triggers_fired}
        # Compound Act: calendar leg (2020) passed, daily_high<=85 x2 and
        # daily_low>=40 x1 met by seeded weather. Condition Act needs
        # daily_low>=68 sustained 3 -- 65 fails it.
        assert "Compound Act" in fired
        assert "Condition Act" not in fired
        status = db.execute("SELECT status FROM activities WHERE name='Compound Act'").fetchone()["status"]
        assert status == "preparing"


class TestToolSurface:
    def test_server_lists_fourteen_tools(self):
        # 11 v1 tools + delete_activity (43) + add_step (44) + undo (45)
        import server
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert len(names) == 14
        assert "create_domain" not in names
        assert "create_activity" not in names
        assert {"load_domain", "add_activities", "update_activity", "update_step", "complete_activity"} <= names

    def test_removed_tools_return_unknown(self, db_path):
        import server
        result = asyncio.run(server.call_tool("create_domain", {"name": "X"}))
        assert "Unknown tool" in json.loads(result.content[0].text)["error"]
