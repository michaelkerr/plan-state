#!/usr/bin/env python3
"""Test Todoist completion polling: summary reporting, no re-reporting, and
main() ordering (completions must be polled before the overdue check)."""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))

import daily_sync

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    """Stub for the requests module: every GET returns a completed task."""

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {"checked": True}
        self.get_calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append(url)
        return FakeResponse(self.payload)


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name) VALUES ('dom1', 'Yard')")
    conn.execute(
        "INSERT INTO activities (id, domain_id, name, status) VALUES ('act1', 'dom1', 'Sync Test Activity', 'active')"
    )
    conn.execute(
        """INSERT INTO steps (id, activity_id, name, step_type, status, due_date)
           VALUES ('step1', 'act1', 'Confirm test task', 'prep', 'due', '2026-07-03')"""
    )
    conn.execute(
        """INSERT INTO todoist_sync (plan_item_id, plan_item_type, todoist_task_id, sync_status)
           VALUES ('act1', 'activity', 'T1', 'synced'), ('step1', 'step', 'T2', 'synced')"""
    )
    conn.commit()
    return conn


class TestPollCompletionsReporting:
    def test_completed_tasks_reported_in_summary(self, db, monkeypatch):
        fake = FakeRequests()
        monkeypatch.setattr(daily_sync, "requests", fake)
        summary = daily_sync.SyncSummary()

        daily_sync._todoist_poll_completions(db, {}, summary)

        assert sorted(summary.todoist_completed) == ["Confirm test task", "Sync Test Activity"]
        assert db.execute("SELECT status FROM activities WHERE id='act1'").fetchone()["status"] == "completed"
        assert db.execute("SELECT status FROM steps WHERE id='step1'").fetchone()["status"] == "completed"

    def test_already_completed_items_not_polled_or_rereported(self, db, monkeypatch):
        fake = FakeRequests()
        monkeypatch.setattr(daily_sync, "requests", fake)

        first = daily_sync.SyncSummary()
        daily_sync._todoist_poll_completions(db, {}, first)
        assert len(first.todoist_completed) == 2

        # Next day's run: plan items are already completed — no API calls,
        # no duplicate summary entries, no duplicate activity_log rows.
        fake.get_calls.clear()
        second = daily_sync.SyncSummary()
        daily_sync._todoist_poll_completions(db, {}, second)

        assert fake.get_calls == []
        assert second.todoist_completed == []
        log_count = db.execute(
            "SELECT COUNT(*) as c FROM activity_log WHERE action='status_change'"
        ).fetchone()["c"]
        assert log_count == 2

    def test_incomplete_tasks_not_reported(self, db, monkeypatch):
        fake = FakeRequests(payload={"checked": False})
        monkeypatch.setattr(daily_sync, "requests", fake)
        summary = daily_sync.SyncSummary()

        daily_sync._todoist_poll_completions(db, {}, summary)

        assert summary.todoist_completed == []
        assert db.execute("SELECT status FROM steps WHERE id='step1'").fetchone()["status"] == "due"


class TestMainOrdering:
    def test_overdue_check_runs_after_todoist_sync(self, monkeypatch):
        """A task completed in Todoist must not be reported overdue by the same
        run that detects the completion — so the poll happens first."""
        calls = []

        monkeypatch.setattr(daily_sync.os.path, "exists", lambda p: True)
        monkeypatch.setattr(daily_sync, "get_db", lambda: type(
            "FakeConn", (), {"commit": lambda s: None, "rollback": lambda s: None, "close": lambda s: None}
        )())
        monkeypatch.setattr(daily_sync, "save_output", lambda s: calls.append("save_output"))
        for fn in ("pull_weather", "evaluate_conditions", "evaluate_triggers",
                   "reestimate_dates", "check_overdue", "todoist_sync"):
            monkeypatch.setattr(daily_sync, fn, lambda conn, summary, _fn=fn: calls.append(_fn))
        monkeypatch.setattr(daily_sync, "enqueue_todoist_items", lambda conn: calls.append("enqueue_todoist_items"))

        with pytest.raises(SystemExit) as exc:
            daily_sync.main()

        assert exc.value.code == 0
        assert calls.index("todoist_sync") < calls.index("check_overdue")
        assert calls.index("enqueue_todoist_items") < calls.index("todoist_sync")
