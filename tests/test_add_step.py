#!/usr/bin/env python3
"""Step 44: add_step -- attach a step to an existing activity, due date
derived from the parent's trigger_date."""

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
    conn.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
        "VALUES ('a1','d1','Sow','watching','calendar','{\"type\": \"calendar\", \"date\": \"2099-06-01\"}','2099-06-01')")
    conn.execute(
        "INSERT INTO activities (id, domain_id, name, status) VALUES ('a2','d1','Mulch','active')")
    conn.commit()
    yield conn
    conn.close()


def call(args):
    import server
    conn = server.get_db()
    try:
        return json.loads(server._add_step(conn, args).content[0].text)
    finally:
        conn.close()


class TestAddStep:
    def test_prep_due_before_trigger(self, db):
        out = call({"activity_id": "a1", "name": "Rake bed", "step_type": "prep", "lead_days": 5})
        assert "error" not in out
        assert out["due_date"] == "2099-05-27"
        assert out["status"] == "pending"
        assert out["activity_name"] == "Sow"

    def test_follow_up_due_after_trigger(self, db):
        out = call({"activity_id": "a1", "name": "Water in", "step_type": "follow_up", "lead_days": 3})
        assert out["due_date"] == "2099-06-04"

    def test_no_trigger_parent_null_due(self, db):
        out = call({"activity_id": "a2", "name": "Buy straw", "step_type": "prep", "lead_days": 3})
        assert "error" not in out
        assert out["due_date"] is None

    def test_parent_cascade_reaches_new_step(self, db):
        out = call({"activity_id": "a1", "name": "Rake bed", "step_type": "prep", "lead_days": 5})
        import server
        conn = server.get_db()
        try:
            server._update_activity(conn, {"activity_id": "a1", "trigger_date": "2099-07-01"})
        finally:
            conn.close()
        due = db.execute("SELECT due_date FROM steps WHERE id=?", (out["id"],)).fetchone()["due_date"]
        assert due == "2099-06-26"

    def test_appends_sort_order(self, db):
        db.execute("INSERT INTO steps (id, activity_id, name, step_type, sort_order) "
                   "VALUES ('s0','a1','Existing','prep',4)")
        db.commit()
        out = call({"activity_id": "a1", "name": "Later", "step_type": "prep", "lead_days": 0})
        so = db.execute("SELECT sort_order FROM steps WHERE id=?", (out["id"],)).fetchone()["sort_order"]
        assert so == 5

    def test_logged_as_created(self, db):
        out = call({"activity_id": "a1", "name": "Rake bed", "step_type": "prep", "lead_days": 5})
        entry = db.execute(
            "SELECT * FROM activity_log WHERE item_type='step' AND item_id=? AND action='created'",
            (out["id"],)).fetchone()
        assert entry is not None
        assert json.loads(entry["new_value"])["name"] == "Rake bed"


class TestValidation:
    def test_missing_activity(self, db):
        out = call({"activity_id": "nope", "name": "X", "step_type": "prep", "lead_days": 1})
        assert "error" in out

    def test_bad_step_type(self, db):
        out = call({"activity_id": "a1", "name": "X", "step_type": "someday", "lead_days": 1})
        assert "error" in out

    def test_negative_lead_days(self, db):
        out = call({"activity_id": "a1", "name": "X", "step_type": "prep", "lead_days": -2})
        assert "error" in out

    def test_tool_listed(self):
        import asyncio
        import server
        names = {t.name for t in asyncio.run(server.list_tools())}
        assert "add_step" in names
