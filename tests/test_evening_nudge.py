#!/usr/bin/env python3
"""Test the evening nudge (Step 21): lists items still open today, silent when
there is nothing due. Replaces Todoist's due-time reminder function."""

import os
import sqlite3

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import evening_nudge

TODAY = "2026-07-19"


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(os.path.join(ROOT, "schema.sql")) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1', 'Garden', 'Murfreesboro,TN,US')")
    yield conn
    conn.close()


def add_activity(conn, aid, name, status, trigger_date=None, group_name=None):
    conn.execute(
        "INSERT INTO activities (id, domain_id, name, group_name, status, trigger_type, trigger_def, trigger_date)"
        " VALUES (?, 'd1', ?, ?, ?, 'calendar', '{}', ?)",
        (aid, name, group_name, status, trigger_date),
    )


def add_step(conn, sid, aid, name, status, due_date):
    conn.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, lead_days, status, due_date)"
        " VALUES (?, ?, ?, 'prep', 0, ?, ?)",
        (sid, aid, name, status, due_date),
    )


def test_step_due_today_is_listed(conn):
    add_activity(conn, "a1", "Transplant Tomatoes", "preparing", TODAY, "Tomatoes")
    add_step(conn, "s1", "a1", "Harden off seedlings", "due", TODAY)
    msg = evening_nudge.build_nudge(conn, TODAY)
    assert msg is not None
    assert "Harden off seedlings" in msg


def test_overdue_step_listed_with_date(conn):
    add_activity(conn, "a1", "Transplant Tomatoes", "active", "2026-07-15")
    add_step(conn, "s1", "a1", "Water in transplants", "pending", "2026-07-16")
    msg = evening_nudge.build_nudge(conn, TODAY)
    assert "Water in transplants" in msg
    assert "2026-07-16" in msg


def test_future_step_not_listed(conn):
    add_activity(conn, "a1", "Transplant Tomatoes", "preparing", "2026-07-25")
    add_step(conn, "s1", "a1", "Prep bed", "pending", "2026-07-22")
    assert evening_nudge.build_nudge(conn, TODAY) is None


def test_step_under_completed_activity_is_listed(conn):
    # v2 (Step 40): step visibility is the step's own state -- a follow-up
    # promoted to 'due' when its activity completed still nudges until done.
    # (v1 hid these; that was the headline visibility bug.)
    add_activity(conn, "a1", "Transplant Tomatoes", "completed", "2026-07-10")
    add_step(conn, "s1", "a1", "Water in transplants", "due", "2026-07-11")
    msg = evening_nudge.build_nudge(conn, TODAY)
    assert msg is not None
    assert "Water in transplants" in msg


def test_completed_step_not_listed(conn):
    add_activity(conn, "a1", "Transplant Tomatoes", "active", TODAY)
    add_step(conn, "s1", "a1", "Water in transplants", "completed", TODAY)
    # the fired activity itself is still open, so it appears -- but not its step
    msg = evening_nudge.build_nudge(conn, TODAY)
    assert "Water in transplants" not in (msg or "")


def test_fired_activity_due_today_is_listed(conn):
    add_activity(conn, "a1", "Southern Peas: Sow", "active", TODAY, "S1")
    msg = evening_nudge.build_nudge(conn, TODAY)
    assert "Southern Peas: Sow" in msg
    assert "S1" in msg


def test_watching_activity_not_listed(conn):
    # not fired yet -- nothing to do, even if the estimated date has arrived
    add_activity(conn, "a1", "Summer Fungicide Watch", "watching", TODAY)
    assert evening_nudge.build_nudge(conn, TODAY) is None


def test_all_clear_returns_none(conn):
    assert evening_nudge.build_nudge(conn, TODAY) is None


def test_group_prefix_in_lines(conn):
    add_activity(conn, "a1", "Transplant Tomatoes", "active", TODAY, "Tomatoes")
    add_step(conn, "s1", "a1", "Water in transplants", "due", TODAY)
    msg = evening_nudge.build_nudge(conn, TODAY)
    assert "Tomatoes" in msg
    assert "Garden" in msg  # domain named so multi-domain nudges read clearly


def test_long_list_is_capped_but_counted(conn):
    for i in range(15):
        add_activity(conn, f"a{i}", f"Task {i}", "active", TODAY)
    msg = evening_nudge.build_nudge(conn, TODAY)
    assert len([l for l in msg.splitlines() if l.startswith("-")]) <= 10
    assert "5 more" in msg
