#!/usr/bin/env python3
"""Step 41: get_upcoming builds from the shared view layer. Same response
structure; visibility now includes actionable steps under completed parents."""

import inspect
import json
import os
import sqlite3
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
IN_FIVE = (TODAY + timedelta(days=5)).isoformat()
IN_THIRTY = (TODAY + timedelta(days=30)).isoformat()


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


def add_activity(db, aid, status="active", trigger_date=None, sort_order=0):
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_date, sort_order) "
        "VALUES (?,?,?,?,?,?)", (aid, "d1", aid, status, trigger_date, sort_order))
    db.commit()


def add_step(db, sid, aid, status="pending", due_date=None, step_type="prep"):
    db.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
        "VALUES (?,?,?,?,?,?)", (sid, aid, sid, step_type, status, due_date))
    db.commit()


def upcoming(days=14):
    import server
    conn = server.get_db()
    try:
        return json.loads(server._get_upcoming(conn, days)[0].text)
    finally:
        conn.close()


class TestStructureParity:
    def test_response_shape(self, db):
        add_activity(db, "a1", trigger_date=IN_FIVE)
        add_step(db, "s1", "a1", due_date=IN_FIVE)
        out = upcoming()
        assert out["today"] == TODAY.isoformat()
        assert out["cutoff"] == (TODAY + timedelta(days=14)).isoformat()
        item = out["items"][0]
        assert item["id"] == "a1"
        assert item["domain_name"] == "Garden"
        assert item["has_overdue"] is False
        assert item["steps"][0]["id"] == "s1"

    def test_beyond_cutoff_excluded(self, db):
        add_activity(db, "a1", trigger_date=IN_THIRTY)
        assert upcoming(14)["items"] == []

    def test_undated_activity_and_step_included(self, db):
        add_activity(db, "a1", trigger_date=None)
        add_step(db, "s1", "a1", due_date=None)
        out = upcoming()
        assert [i["id"] for i in out["items"]] == ["a1"]
        assert [s["id"] for s in out["items"][0]["steps"]] == ["s1"]

    def test_undated_sorts_last(self, db):
        add_activity(db, "a1", trigger_date=None)
        add_activity(db, "a2", trigger_date=IN_FIVE)
        assert [i["id"] for i in upcoming()["items"]] == ["a2", "a1"]

    def test_has_overdue_flag(self, db):
        add_activity(db, "a1", trigger_date=YESTERDAY)
        add_step(db, "s1", "a1", status="due", due_date=YESTERDAY)
        assert upcoming()["items"][0]["has_overdue"] is True

    def test_closed_steps_not_nested(self, db):
        add_activity(db, "a1", trigger_date=IN_FIVE)
        add_step(db, "s1", "a1", status="completed", due_date=IN_FIVE)
        assert upcoming()["items"][0]["steps"] == []


class TestVisibilityUnification:
    def test_completed_parent_with_actionable_step_appears(self, db):
        add_activity(db, "a1", status="completed", trigger_date=YESTERDAY)
        add_step(db, "f1", "a1", status="due", due_date=YESTERDAY, step_type="follow_up")
        out = upcoming()
        assert [i["id"] for i in out["items"]] == ["a1"]
        item = out["items"][0]
        assert item["status"] == "completed"
        assert [s["id"] for s in item["steps"]] == ["f1"]
        assert item["has_overdue"] is True

    def test_completed_parent_without_open_steps_hidden(self, db):
        add_activity(db, "a1", status="completed", trigger_date=YESTERDAY)
        add_step(db, "f1", "a1", status="completed", due_date=YESTERDAY)
        assert upcoming()["items"] == []

    def test_skipped_parent_stays_hidden(self, db):
        # soft-deleted activities skip their steps too (Step 43); an open step
        # under a skipped parent still surfaces -- the step is real work
        add_activity(db, "a1", status="skipped", trigger_date=YESTERDAY)
        add_step(db, "s1", "a1", status="skipped", due_date=YESTERDAY)
        assert upcoming()["items"] == []

    def test_overdue_count_matches_view(self, db):
        from plansync.engine import get_actionable_items
        add_activity(db, "a1", status="completed")
        add_step(db, "f1", "a1", status="due", due_date=YESTERDAY, step_type="follow_up")
        add_activity(db, "a2", status="active", trigger_date=YESTERDAY)
        add_step(db, "s2", "a2", status="pending", due_date=YESTERDAY)
        out = upcoming()
        nested_overdue = [
            s["id"] for i in out["items"] for s in i["steps"]
            if s["due_date"] and s["due_date"] < TODAY.isoformat()
        ]
        view_overdue = [i["step_id"] for i in get_actionable_items(db)]
        assert sorted(nested_overdue) == sorted(view_overdue)


class TestNoInlineDueSQL:
    def test_no_status_filter_sql_in_get_upcoming(self):
        import server
        src = inspect.getsource(server._get_upcoming)
        assert "a.status IN" not in src and "status IN (" not in src
        assert "get_open_activities" in src and "get_actionable_items" in src
