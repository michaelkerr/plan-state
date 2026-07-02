#!/usr/bin/env python3
"""Test the Todoist enqueue reconciliation pass in daily_sync."""

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    conn.execute("INSERT INTO domains (id, name, location) VALUES ('dom000000001', 'Garden', 'Richmond,VA,US')")
    activities = [
        # (id, name, status)
        ("act0prepare1", "Preparing Activity", "preparing"),
        ("act0active01", "Active Activity", "active"),
        ("act0watching", "Watching Activity", "watching"),
        ("act0complete", "Completed Activity", "completed"),
    ]
    for aid, name, status in activities:
        conn.execute(
            "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
            "VALUES (?, 'dom000000001', ?, ?, 'calendar', '{\"type\":\"calendar\",\"date\":\"2026-07-01\"}', '2026-07-01')",
            (aid, name, status),
        )
    steps = [
        # (id, activity_id, name, status, due_date)
        ("step0pending", "act0prepare1", "Pending step with date", "pending", "2026-07-05"),
        ("step0due0001", "act0prepare1", "Due step", "due", "2026-06-30"),
        ("step0nodate1", "act0prepare1", "Pending step no date", "pending", None),
        ("step0done001", "act0prepare1", "Completed step", "completed", "2026-06-28"),
        ("step0watch01", "act0watching", "Step of watching activity", "pending", "2026-07-05"),
    ]
    for sid, aid, name, status, due in steps:
        conn.execute(
            "INSERT INTO steps (id, activity_id, name, step_type, lead_days, status, due_date) "
            "VALUES (?, ?, ?, 'prep', 1, ?, ?)",
            (sid, aid, name, status, due),
        )
    conn.commit()
    return conn


def enqueue(conn):
    import daily_sync
    daily_sync.enqueue_todoist_items(conn)
    conn.commit()


def sync_rows(conn):
    return {
        (r["plan_item_id"], r["plan_item_type"]): r["sync_status"]
        for r in conn.execute("SELECT * FROM todoist_sync").fetchall()
    }


class TestEnqueue:
    def test_preparing_and_active_activities_enqueued(self, db):
        enqueue(db)
        rows = sync_rows(db)
        assert rows[("act0prepare1", "activity")] == "pending_create"
        assert rows[("act0active01", "activity")] == "pending_create"

    def test_watching_and_completed_activities_not_enqueued(self, db):
        enqueue(db)
        rows = sync_rows(db)
        assert ("act0watching", "activity") not in rows
        assert ("act0complete", "activity") not in rows

    def test_eligible_steps_enqueued(self, db):
        enqueue(db)
        rows = sync_rows(db)
        assert rows[("step0pending", "step")] == "pending_create"
        assert rows[("step0due0001", "step")] == "pending_create"

    def test_ineligible_steps_not_enqueued(self, db):
        enqueue(db)
        rows = sync_rows(db)
        assert ("step0nodate1", "step") not in rows  # no due date
        assert ("step0done001", "step") not in rows  # completed
        assert ("step0watch01", "step") not in rows  # parent still watching

    def test_idempotent(self, db):
        enqueue(db)
        first = sync_rows(db)
        enqueue(db)
        assert sync_rows(db) == first

    def test_existing_sync_rows_untouched(self, db):
        db.execute(
            "INSERT INTO todoist_sync (plan_item_id, plan_item_type, todoist_task_id, sync_status) "
            "VALUES ('act0prepare1', 'activity', 'task123', 'synced')"
        )
        db.commit()
        enqueue(db)
        rows = sync_rows(db)
        assert rows[("act0prepare1", "activity")] == "synced"
