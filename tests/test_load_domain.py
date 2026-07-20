#!/usr/bin/env python3
"""Test the load_domain MCP tool against a temporary SQLite database."""

import json
import os
import sqlite3
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
EXAMPLES_DIR = os.path.join(ROOT, "examples")


def load_example(name):
    with open(os.path.join(EXAMPLES_DIR, name)) as f:
        return json.load(f)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
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
    return conn


@pytest.fixture(autouse=True)
def patch_db_path(db_path, monkeypatch):
    monkeypatch.setenv("PLANSYNC_DB", db_path)
    import server


def call_load_domain(definition):
    import server
    conn = server.get_db()
    try:
        result = server._load_domain(conn, {"definition": definition})
        text = result[0].text
        return json.loads(text)
    finally:
        conn.close()


class TestLoadDomainValid:
    def test_lawn_care_creates_domain(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)
        assert "error" not in result
        assert result["name"] == "Cool-Season Lawn Care"
        assert result["id"]

        row = db.execute("SELECT * FROM domains WHERE id=?", (result["id"],)).fetchone()
        assert row is not None
        assert row["name"] == "Cool-Season Lawn Care"
        assert row["location"] == "Richmond,VA,US"

    def test_lawn_care_creates_all_activities(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)
        assert len(result["activities"]) == 4

        rows = db.execute("SELECT * FROM activities WHERE domain_id=?", (result["id"],)).fetchall()
        assert len(rows) == 4

    def test_lawn_care_creates_steps(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)

        total_steps = sum(len(a.get("steps", [])) for a in result["activities"])
        assert total_steps > 0

        db_steps = db.execute(
            "SELECT s.* FROM steps s JOIN activities a ON s.activity_id=a.id WHERE a.domain_id=?",
            (result["id"],),
        ).fetchall()
        assert len(db_steps) == total_steps

    def test_lawn_care_creates_conditions(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)

        db_conditions = db.execute(
            "SELECT c.* FROM conditions c JOIN activities a ON c.activity_id=a.id WHERE a.domain_id=?",
            (result["id"],),
        ).fetchall()
        assert len(db_conditions) == 1  # only pre-emergent has explicit conditions

    def test_dependency_refs_resolved(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)

        spring_fert = next(a for a in result["activities"] if a["name"] == "Spring Fertilizer Application")
        pre_emergent = next(a for a in result["activities"] if a["name"] == "Apply Pre-Emergent Herbicide")

        row = db.execute("SELECT trigger_def FROM activities WHERE id=?", (spring_fert["id"],)).fetchone()
        tdef = json.loads(row["trigger_def"])
        assert tdef["activity_id"] == pre_emergent["id"]
        assert "activity_ref" not in tdef

    def test_fall_garden_creates_domain(self, db):
        definition = load_example("fall-garden.json")
        result = call_load_domain(definition)
        assert "error" not in result
        assert result["name"] == "Zone 7a Fall Garden"
        assert len(result["activities"]) == 5

    def test_fall_garden_dependency_chain(self, db):
        definition = load_example("fall-garden.json")
        result = call_load_domain(definition)

        transplant = next(a for a in result["activities"] if a["name"] == "Transplant Broccoli to Beds")
        start = next(a for a in result["activities"] if a["name"] == "Start Broccoli Transplants Indoors")

        row = db.execute("SELECT trigger_def FROM activities WHERE id=?", (transplant["id"],)).fetchone()
        tdef = json.loads(row["trigger_def"])
        assert tdef["activity_id"] == start["id"]

    def test_calendar_trigger_date_computed(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)

        mower = next(a for a in result["activities"] if a["name"] == "Sharpen Mower Blades")
        row = db.execute("SELECT trigger_date FROM activities WHERE id=?", (mower["id"],)).fetchone()
        assert row["trigger_date"] == "2027-03-01"

    def test_step_dates_cascaded(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)

        mower = next(a for a in result["activities"] if a["name"] == "Sharpen Mower Blades")
        steps = db.execute(
            "SELECT * FROM steps WHERE activity_id=? ORDER BY sort_order", (mower["id"],)
        ).fetchall()

        remove_blades = next(s for s in steps if s["name"] == "Remove blades")
        assert remove_blades["due_date"] == "2027-02-26"  # 3 days before Mar 1

    def test_activity_log_created(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)

        log_entry = db.execute(
            "SELECT * FROM activity_log WHERE item_type='domain' AND action='created'"
        ).fetchone()
        assert log_entry is not None

    def test_all_activities_start_watching(self, db):
        definition = load_example("lawn-care.json")
        result = call_load_domain(definition)

        rows = db.execute(
            "SELECT status FROM activities WHERE domain_id=?", (result["id"],)
        ).fetchall()
        assert all(r["status"] == "watching" for r in rows)


class TestLoadDomainInvalid:
    def test_missing_name_returns_error(self, db):
        result = call_load_domain({"activities": [{"name": "X", "trigger_type": "calendar", "trigger_def": {"type": "calendar", "date": "2027-01-01"}}]})
        assert "error" in result

    def test_missing_activities_returns_error(self, db):
        result = call_load_domain({"name": "Test"})
        assert "error" in result

    def test_empty_activities_returns_error(self, db):
        result = call_load_domain({"name": "Test", "activities": []})
        assert "error" in result

    def test_invalid_trigger_type_returns_error(self, db):
        result = call_load_domain({
            "name": "Test",
            "activities": [{"name": "X", "trigger_type": "magic", "trigger_def": {"type": "magic"}}],
        })
        assert "error" in result

    def test_unresolvable_dependency_ref_returns_error(self, db):
        result = call_load_domain({
            "name": "Test",
            "activities": [{
                "name": "X",
                "trigger_type": "dependency",
                "trigger_def": {"type": "dependency", "activity_ref": "Nonexistent Activity", "event": "completed"},
            }],
        })
        assert "error" in result

    def test_rollback_on_error(self, db):
        result = call_load_domain({
            "name": "Test",
            "activities": [{
                "name": "Good Activity",
                "trigger_type": "calendar",
                "trigger_def": {"type": "calendar", "date": "2027-01-01"},
            }, {
                "name": "Bad Activity",
                "trigger_type": "dependency",
                "trigger_def": {"type": "dependency", "activity_ref": "Nonexistent", "event": "completed"},
            }],
        })
        assert "error" in result

        domains = db.execute("SELECT COUNT(*) as cnt FROM domains").fetchone()["cnt"]
        activities = db.execute("SELECT COUNT(*) as cnt FROM activities").fetchone()["cnt"]
        assert domains == 0
        assert activities == 0

    def test_duplicate_domain_name_returns_error(self, db):
        definition = load_example("lawn-care.json")
        call_load_domain(definition)
        result = call_load_domain(definition)
        assert "error" in result
        assert "already exists" in result["error"].lower()
