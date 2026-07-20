#!/usr/bin/env python3
"""Test the add_activities MCP tool: amending an existing domain."""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")


BASE_DOMAIN = {
    "name": "Test Garden",
    "location": "Richmond,VA,US",
    "activities": [
        {
            "name": "Start Tomato Seeds",
            "group_name": "Tomatoes",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2027-02-15"},
        },
        {
            "name": "Plant Garlic",
            "group_name": "Garlic",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2026-10-15"},
            "sort_order": 5,
        },
    ],
}

NEW_ACTIVITIES = [
    {
        "name": "Transplant Tomatoes",
        "group_name": "Tomatoes",
        "trigger_type": "dependency",
        "trigger_def": {
            "type": "dependency",
            "activity_ref": "Start Tomato Seeds",
            "event": "completed",
            "offset_days": 42,
        },
        "steps": [
            {"name": "Harden off seedlings", "step_type": "prep", "lead_days": 7},
            {"name": "Water deeply", "step_type": "follow_up", "lead_days": 0},
        ],
    },
    {
        "name": "Tomato Harvest Watch",
        "group_name": "Tomatoes",
        "trigger_type": "dependency",
        "trigger_def": {
            "type": "dependency",
            "activity_ref": "Transplant Tomatoes",
            "event": "completed",
            "offset_days": 60,
        },
    },
    {
        "name": "Harvest Garlic",
        "group_name": "Garlic",
        "trigger_type": "compound",
        "trigger_def": {
            "type": "compound",
            "operator": "AND",
            "conditions": [
                {"type": "calendar", "after": "2027-06-20"},
                {"type": "condition", "all": [
                    {"metric": "daily_high", "operator": ">=", "value": 75, "sustained_days": 2}
                ]},
            ],
        },
    },
]


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


def call_tool(fn_name, args):
    import server
    conn = server.get_db()
    try:
        result = getattr(server, fn_name)(conn, args)
        return json.loads(result[0].text)
    finally:
        conn.close()


@pytest.fixture
def loaded_domain(db_path):
    return call_tool("_load_domain", {"definition": BASE_DOMAIN})


class TestAddActivitiesValid:
    def test_adds_activities(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        assert "error" not in result
        assert len(result["activities"]) == 3

        count = db.execute(
            "SELECT COUNT(*) as cnt FROM activities WHERE domain_id=?", (loaded_domain["id"],)
        ).fetchone()["cnt"]
        assert count == 5  # 2 existing + 3 new

    def test_ref_to_existing_activity_resolved(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        seed_start = next(a for a in loaded_domain["activities"] if a["name"] == "Start Tomato Seeds")
        transplant = next(a for a in result["activities"] if a["name"] == "Transplant Tomatoes")

        row = db.execute("SELECT trigger_def FROM activities WHERE id=?", (transplant["id"],)).fetchone()
        tdef = json.loads(row["trigger_def"])
        assert tdef["activity_id"] == seed_start["id"]
        assert "activity_ref" not in tdef

    def test_ref_within_batch_resolved(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        transplant = next(a for a in result["activities"] if a["name"] == "Transplant Tomatoes")
        harvest = next(a for a in result["activities"] if a["name"] == "Tomato Harvest Watch")

        row = db.execute("SELECT trigger_def FROM activities WHERE id=?", (harvest["id"],)).fetchone()
        tdef = json.loads(row["trigger_def"])
        assert tdef["activity_id"] == transplant["id"]

    def test_steps_and_dates_created(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        transplant = next(a for a in result["activities"] if a["name"] == "Transplant Tomatoes")
        steps = db.execute("SELECT * FROM steps WHERE activity_id=?", (transplant["id"],)).fetchall()
        assert len(steps) == 2

        harvest_garlic = next(a for a in result["activities"] if a["name"] == "Harvest Garlic")
        row = db.execute("SELECT trigger_date FROM activities WHERE id=?", (harvest_garlic["id"],)).fetchone()
        assert row["trigger_date"] == "2027-06-20"

    def test_conditions_derived_from_trigger_def(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        harvest_garlic = next(a for a in result["activities"] if a["name"] == "Harvest Garlic")
        conds = db.execute("SELECT * FROM conditions WHERE activity_id=?", (harvest_garlic["id"],)).fetchall()
        assert len(conds) == 1
        assert conds[0]["condition_type"] == "temperature"
        assert json.loads(conds[0]["definition"])["metric"] == "daily_high"

    def test_group_name_persisted(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        transplant = next(a for a in result["activities"] if a["name"] == "Transplant Tomatoes")
        row = db.execute("SELECT group_name FROM activities WHERE id=?", (transplant["id"],)).fetchone()
        assert row["group_name"] == "Tomatoes"

    def test_new_activities_start_watching(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        ids = [a["id"] for a in result["activities"]]
        rows = db.execute(
            f"SELECT status FROM activities WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        assert all(r["status"] == "watching" for r in rows)

    def test_sort_order_continues_after_existing(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        ids = [a["id"] for a in result["activities"]]
        rows = db.execute(
            f"SELECT sort_order FROM activities WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        # existing max sort_order is 5 (Plant Garlic); new ones come after
        assert all(r["sort_order"] > 5 for r in rows)

    def test_activity_log_entries(self, db, loaded_domain):
        call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": NEW_ACTIVITIES,
        })
        cnt = db.execute(
            "SELECT COUNT(*) as cnt FROM activity_log WHERE item_type='activity' AND action='created'"
        ).fetchone()["cnt"]
        assert cnt == 5  # 2 from load_domain + 3 from add_activities


class TestAddActivitiesInvalid:
    def test_unknown_domain_returns_error(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": "nonexistent00",
            "activities": NEW_ACTIVITIES,
        })
        assert "error" in result

    def test_empty_activities_returns_error(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": [],
        })
        assert "error" in result

    def test_duplicate_of_existing_name_rejected(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": [{
                "name": "Plant Garlic",
                "trigger_type": "calendar",
                "trigger_def": {"type": "calendar", "date": "2027-10-15"},
            }],
        })
        assert "error" in result

    def test_unresolvable_ref_rejected(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": [{
                "name": "Orphan",
                "trigger_type": "dependency",
                "trigger_def": {"type": "dependency", "activity_ref": "Does Not Exist", "event": "completed"},
            }],
        })
        assert "error" in result

    def test_invalid_batch_rolls_back(self, db, loaded_domain):
        result = call_tool("_add_activities", {
            "domain_id": loaded_domain["id"],
            "activities": [
                {
                    "name": "Good One",
                    "trigger_type": "calendar",
                    "trigger_def": {"type": "calendar", "date": "2027-01-01"},
                },
                {
                    "name": "Bad One",
                    "trigger_type": "dependency",
                    "trigger_def": {"type": "dependency", "activity_ref": "Nope", "event": "completed"},
                },
            ],
        })
        assert "error" in result
        count = db.execute(
            "SELECT COUNT(*) as cnt FROM activities WHERE domain_id=?", (loaded_domain["id"],)
        ).fetchone()["cnt"]
        assert count == 2  # only the originals
