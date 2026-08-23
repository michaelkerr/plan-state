#!/usr/bin/env python3
"""Step 33: update_step tool -- edit step fields and complete individual steps."""

import json
import os
import sqlite3

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")

DOMAIN = {
    "name": "Step Update Test",
    "location": "Murfreesboro,TN,US",
    "activities": [
        {
            "name": "Test Activity",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2099-06-01"},
            "steps": [
                {"name": "Prep step", "step_type": "prep", "lead_days": 5,
                 "description": "Original prep desc"},
                {"name": "Follow step", "step_type": "follow_up", "lead_days": 10},
            ],
        },
    ],
}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("PLANSYNC_DB", path)
    monkeypatch.setenv("PLANSYNC_CLIENT", "claude")
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


@pytest.fixture
def loaded_domain(db_path):
    """Load the test domain and return (domain_id, activity_id, step_ids)."""
    import server
    from plansync.engine import get_db
    conn = get_db()
    result = json.loads(server._load_domain(conn, {"definition": DOMAIN}).content[0].text)
    conn.close()
    did = result["id"]
    act = result["activities"][0]
    aid = act["id"]
    step_ids = [s["id"] for s in act["steps"]]
    return did, aid, step_ids


def call_update_step(args):
    import server
    from plansync.engine import get_db
    conn = get_db()
    result = json.loads(server._update_step(conn, args).content[0].text)
    conn.close()
    return result


# ── Name and description updates ──────────────────────────────

def test_update_step_name(loaded_domain):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    result = call_update_step({"step_id": prep_id, "name": "Renamed prep"})
    assert result["name"] == "Renamed prep"
    assert result["activity_name"] == "Test Activity"


def test_update_step_description(loaded_domain):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    result = call_update_step({"step_id": prep_id, "description": "New desc"})
    assert result["description"] == "New desc"
    assert result["name"] == "Prep step"  # unchanged


# ── Status changes ────────────────────────────────────────────

def test_complete_step_sets_completed_at(loaded_domain):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    result = call_update_step({"step_id": prep_id, "status": "completed"})
    assert result["status"] == "completed"
    assert result["completed_at"] is not None


def test_uncomplete_step_clears_completed_at(loaded_domain):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    # Complete it first
    call_update_step({"step_id": prep_id, "status": "completed"})
    # Then un-complete
    result = call_update_step({"step_id": prep_id, "status": "pending"})
    assert result["status"] == "pending"
    assert result["completed_at"] is None


def test_skip_step(loaded_domain):
    _, _, step_ids = loaded_domain
    result = call_update_step({"step_id": step_ids[1], "status": "skipped"})
    assert result["status"] == "skipped"


# ── lead_days / step_type changes re-derive due_date ──────────

def test_change_lead_days_rederives_due(loaded_domain):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    # Original: prep, lead_days=5, trigger=2099-06-01 -> due = 2099-05-27
    result = call_update_step({"step_id": prep_id, "lead_days": 10})
    # New: prep, lead_days=10, trigger=2099-06-01 -> due = 2099-05-22
    assert result["due_date"] == "2099-05-22"
    assert result["lead_days"] == 10


def test_change_step_type_rederives_due(loaded_domain):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    # Original: prep, lead_days=5, trigger=2099-06-01 -> due = 2099-05-27
    # Change to follow_up: lead_days=5 -> due = 2099-06-06
    result = call_update_step({"step_id": prep_id, "step_type": "follow_up"})
    assert result["due_date"] == "2099-06-06"
    assert result["step_type"] == "follow_up"


def test_change_both_lead_and_type(loaded_domain):
    _, _, step_ids = loaded_domain
    follow_id = step_ids[1]
    # Original: follow_up, lead_days=10, trigger=2099-06-01 -> due = 2099-06-11
    # Change to prep, lead_days=3 -> due = 2099-05-29
    result = call_update_step({
        "step_id": follow_id, "step_type": "prep", "lead_days": 3
    })
    assert result["due_date"] == "2099-05-29"


# ── Error cases ───────────────────────────────────────────────

def test_step_not_found(loaded_domain):
    result = call_update_step({"step_id": "nonexistent"})
    assert "error" in result


def test_no_fields_to_update(loaded_domain):
    _, _, step_ids = loaded_domain
    result = call_update_step({"step_id": step_ids[0]})
    assert "error" in result
    assert "No fields" in result["error"]


# ── Activity log entries ──────────────────────────────────────

def test_status_change_logged(loaded_domain, db):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    call_update_step({"step_id": prep_id, "status": "completed"})
    log = db.execute(
        "SELECT * FROM activity_log WHERE item_type='step' AND item_id=? AND action='status_change'",
        (prep_id,),
    ).fetchone()
    assert log is not None
    new = json.loads(log["new_value"])
    assert new["status"] == "completed"


def test_name_change_logged(loaded_domain, db):
    _, _, step_ids = loaded_domain
    prep_id = step_ids[0]
    call_update_step({"step_id": prep_id, "name": "Better name"})
    log = db.execute(
        "SELECT * FROM activity_log WHERE item_type='step' AND item_id=? AND action='manual_update'",
        (prep_id,),
    ).fetchone()
    assert log is not None
    old = json.loads(log["old_value"])
    new = json.loads(log["new_value"])
    assert old["name"] == "Prep step"
    assert new["name"] == "Better name"


# ── Parent context in response ────────────────────────────────

def test_response_includes_activity_context(loaded_domain):
    _, _, step_ids = loaded_domain
    result = call_update_step({"step_id": step_ids[0], "name": "X"})
    assert result["activity_name"] == "Test Activity"
    assert "activity_group" in result
