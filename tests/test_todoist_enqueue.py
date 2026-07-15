#!/usr/bin/env python3
"""Test the Todoist enqueue reconciliation pass in daily_sync."""

import os
import sqlite3
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")

TODAY = date.today()
IN_WEEK = (TODAY + timedelta(days=3)).isoformat()
PAST = (TODAY - timedelta(days=5)).isoformat()
BEYOND_WEEK = (TODAY + timedelta(days=30)).isoformat()


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    conn.execute("INSERT INTO domains (id, name, location) VALUES ('dom000000001', 'Garden', 'Richmond,VA,US')")
    activities = [
        # (id, name, status, trigger_date)
        ("act0prepare1", "Preparing Activity", "preparing", PAST),
        ("act0active01", "Active Activity", "active", PAST),
        ("act0watchwk1", "Watching, this week", "watching", IN_WEEK),
        ("act0watchpst", "Watching, date slipped past", "watching", PAST),
        ("act0watchfar", "Watching, next month", "watching", BEYOND_WEEK),
        ("act0watchnod", "Watching, condition-based", "watching", None),
        ("act0complete", "Completed Activity", "completed", PAST),
    ]
    for aid, name, status, tdate in activities:
        conn.execute(
            "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
            "VALUES (?, 'dom000000001', ?, ?, 'calendar', '{\"type\":\"calendar\"}', ?)",
            (aid, name, status, tdate),
        )
    steps = [
        # (id, activity_id, name, status, due_date)
        ("step0pending", "act0prepare1", "Pending step with date", "pending", IN_WEEK),
        ("step0due0001", "act0prepare1", "Due step", "due", PAST),
        ("step0faroff1", "act0prepare1", "Far-off step of fired activity", "pending", BEYOND_WEEK),
        ("step0nodate1", "act0prepare1", "Pending step no date", "pending", None),
        ("step0done001", "act0prepare1", "Completed step", "completed", PAST),
        ("step0watchwk", "act0watchwk1", "This-week step of this-week watcher", "pending", IN_WEEK),
        ("step0watchfr", "act0watchwk1", "Far-off step of this-week watcher", "pending", BEYOND_WEEK),
        ("step0watchno", "act0watchfar", "Step of next-month watcher", "pending", IN_WEEK),
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

    def test_completed_activities_not_enqueued(self, db):
        enqueue(db)
        assert ("act0complete", "activity") not in sync_rows(db)

    def test_eligible_steps_enqueued(self, db):
        enqueue(db)
        rows = sync_rows(db)
        assert rows[("step0pending", "step")] == "pending_create"
        assert rows[("step0due0001", "step")] == "pending_create"

    def test_fired_activity_steps_enqueued_regardless_of_date(self, db):
        enqueue(db)
        assert sync_rows(db)[("step0faroff1", "step")] == "pending_create"

    def test_ineligible_steps_not_enqueued(self, db):
        enqueue(db)
        rows = sync_rows(db)
        assert ("step0nodate1", "step") not in rows  # no due date
        assert ("step0done001", "step") not in rows  # completed

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
        assert sync_rows(db)[("act0prepare1", "activity")] == "synced"


class TestLookahead:
    """Watching activities dated within the look-ahead horizon reach Todoist
    early, so the week's priorities appear together (mirrors the Telegram
    briefing's 7-day window)."""

    def test_watching_within_week_enqueued(self, db):
        enqueue(db)
        assert sync_rows(db)[("act0watchwk1", "activity")] == "pending_create"

    def test_watching_with_past_date_enqueued(self, db):
        enqueue(db)
        assert sync_rows(db)[("act0watchpst", "activity")] == "pending_create"

    def test_watching_beyond_horizon_not_enqueued(self, db):
        enqueue(db)
        assert ("act0watchfar", "activity") not in sync_rows(db)

    def test_watching_without_date_not_enqueued(self, db):
        enqueue(db)
        assert ("act0watchnod", "activity") not in sync_rows(db)

    def test_this_week_steps_of_watching_activity_enqueued(self, db):
        enqueue(db)
        assert sync_rows(db)[("step0watchwk", "step")] == "pending_create"

    def test_far_off_steps_of_watching_activity_not_enqueued(self, db):
        enqueue(db)
        assert ("step0watchfr", "step") not in sync_rows(db)

    def test_steps_of_beyond_horizon_watcher_not_enqueued(self, db):
        enqueue(db)
        assert ("step0watchno", "step") not in sync_rows(db)
