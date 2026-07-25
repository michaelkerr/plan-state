#!/usr/bin/env python3
"""Step 39: actionable_items view -- step visibility from the step's own
state, independent of parent activity status."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from plansync.engine import get_actionable_items  # noqa: E402

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
MIGRATE_SCRIPT = os.path.join(ROOT, "scripts", "migrate-actionable-view.py")

TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','Garden','X')")
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d2','Yard','Y')")
    yield conn
    conn.close()


def add_activity(db, aid, status, domain="d1"):
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status) VALUES (?,?,?,?)",
        (aid, domain, f"Activity {aid}", status),
    )


def add_step(db, sid, aid, status="pending", due_date=None, step_type="prep"):
    db.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
        "VALUES (?,?,?,?,?,?)",
        (sid, aid, f"Step {sid}", step_type, status, due_date),
    )


def view_ids(db):
    return {r["step_id"] for r in db.execute("SELECT step_id FROM actionable_items")}


class TestViewVisibility:
    def test_steps_visible_from_all_parent_statuses(self, db):
        for i, status in enumerate(("watching", "preparing", "active", "completed", "skipped")):
            add_activity(db, f"a{i}", status)
            add_step(db, f"s{i}", f"a{i}", status="pending", due_date=TODAY.isoformat())
        assert view_ids(db) == {"s0", "s1", "s2", "s3", "s4"}

    def test_follow_up_on_completed_activity_appears(self, db):
        # The v1 headline bug: completed parents hid their follow-up steps
        add_activity(db, "a1", "completed")
        add_step(db, "f1", "a1", status="due", due_date=TODAY.isoformat(), step_type="follow_up")
        assert view_ids(db) == {"f1"}

    def test_future_step_not_included(self, db):
        add_activity(db, "a1", "active")
        add_step(db, "s1", "a1", status="pending", due_date=TOMORROW)
        assert view_ids(db) == set()

    def test_overdue_step_included(self, db):
        add_activity(db, "a1", "active")
        add_step(db, "s1", "a1", status="due", due_date=YESTERDAY)
        assert view_ids(db) == {"s1"}

    def test_closed_and_dateless_steps_excluded(self, db):
        add_activity(db, "a1", "active")
        add_step(db, "s1", "a1", status="completed", due_date=TODAY.isoformat())
        add_step(db, "s2", "a1", status="skipped", due_date=TODAY.isoformat())
        add_step(db, "s3", "a1", status="pending", due_date=None)
        assert view_ids(db) == set()

    def test_view_carries_context_columns(self, db):
        add_activity(db, "a1", "active")
        add_step(db, "s1", "a1", status="due", due_date=TODAY.isoformat())
        row = db.execute("SELECT * FROM actionable_items").fetchone()
        assert row["step_name"] == "Step s1"
        assert row["activity_name"] == "Activity a1"
        assert row["activity_status"] == "active"
        assert row["domain_name"] == "Garden"
        assert row["step_type"] == "prep"


class TestOpenStepsBaseView:
    def test_open_steps_has_no_date_filter(self, db):
        add_activity(db, "a1", "active")
        add_step(db, "s1", "a1", status="pending", due_date=TOMORROW)
        add_step(db, "s2", "a1", status="completed", due_date=TODAY.isoformat())
        ids = {r["step_id"] for r in db.execute("SELECT step_id FROM open_steps")}
        assert ids == {"s1"}


class TestEngineFunction:
    def test_matches_raw_view(self, db):
        add_activity(db, "a1", "completed")
        add_step(db, "s1", "a1", status="due", due_date=YESTERDAY, step_type="follow_up")
        add_step(db, "s2", "a1", status="pending", due_date=TOMORROW)
        items = get_actionable_items(db)
        assert {i["step_id"] for i in items} == view_ids(db) == {"s1"}

    def test_as_of_date_widens_window(self, db):
        add_activity(db, "a1", "active")
        add_step(db, "s1", "a1", status="pending", due_date=TODAY.isoformat())
        add_step(db, "s2", "a1", status="pending", due_date=TOMORROW)
        items = get_actionable_items(db, as_of_date=TOMORROW)
        assert {i["step_id"] for i in items} == {"s1", "s2"}

    def test_domain_filter(self, db):
        add_activity(db, "a1", "active", domain="d1")
        add_activity(db, "a2", "active", domain="d2")
        add_step(db, "s1", "a1", status="due", due_date=TODAY.isoformat())
        add_step(db, "s2", "a2", status="due", due_date=TODAY.isoformat())
        items = get_actionable_items(db, domain_id="d2")
        assert {i["step_id"] for i in items} == {"s2"}

    def test_ordered_by_due_date(self, db):
        add_activity(db, "a1", "active")
        add_step(db, "s1", "a1", status="due", due_date=TODAY.isoformat())
        add_step(db, "s2", "a1", status="due", due_date=YESTERDAY)
        items = get_actionable_items(db)
        assert [i["step_id"] for i in items] == ["s2", "s1"]


class TestMigration:
    def test_migration_creates_views_on_old_db(self, tmp_path):
        path = str(tmp_path / "live.db")
        conn = sqlite3.connect(path)
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        conn.executescript("DROP VIEW actionable_items; DROP VIEW open_steps;")
        conn.close()
        result = subprocess.run(
            [sys.executable, MIGRATE_SCRIPT],
            env={**os.environ, "PLANSYNC_DB": path},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        conn = sqlite3.connect(path)
        views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'")}
        assert {"actionable_items", "open_steps", "open_activities"} <= views
        conn.close()

    def test_migration_idempotent(self, tmp_path):
        path = str(tmp_path / "live.db")
        conn = sqlite3.connect(path)
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        conn.close()
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, MIGRATE_SCRIPT],
                env={**os.environ, "PLANSYNC_DB": path},
                capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stderr
