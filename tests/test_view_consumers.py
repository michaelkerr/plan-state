#!/usr/bin/env python3
"""Step 40: evening_nudge and briefing_context read "what's due" from the
shared view layer -- no inline SQL, unified visibility."""

import inspect
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
BRIEFING_SCRIPT = os.path.join(ROOT, "sync", "briefing_context.py")

TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
IN_THREE_DAYS = (TODAY + timedelta(days=3)).isoformat()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','Garden','X')")
    # Completed activity with a promoted follow-up (the v1 invisibility case)
    conn.execute(
        "INSERT INTO activities (id, domain_id, name, status) VALUES ('a1','d1','Transplant','completed')")
    conn.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
        "VALUES ('f1','a1','Water in','follow_up','due',?)", (YESTERDAY,))
    # Watching activity inside the week window
    conn.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_date) "
        "VALUES ('a2','d1','Sow Radish','watching',?)", (IN_THREE_DAYS,))
    # Its prep step due within the week (but not today)
    conn.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
        "VALUES ('p2','a2','Rake bed','prep','pending',?)", (IN_THREE_DAYS,))
    conn.commit()
    conn.close()
    return path


def run_briefing(db_path, out_dir):
    return subprocess.run(
        [sys.executable, BRIEFING_SCRIPT],
        env={**os.environ, "PLANSYNC_DB": db_path, "PLANSYNC_OUTPUT_DIR": out_dir},
        capture_output=True, text=True,
    )


def section(stdout, title):
    return stdout.split(f"=== {title} ===")[1].split("\n===")[0]


class TestBriefingUsesViews:
    def test_due_today_includes_completed_parent_follow_up(self, db_path, tmp_path):
        result = run_briefing(db_path, str(tmp_path / "out"))
        assert result.returncode == 0, result.stderr
        due = json.loads(section(result.stdout, "Due Today or Overdue"))
        assert [d["step"] for d in due] == ["Water in"]
        assert due[0]["activity"] == "Transplant"
        assert due[0]["domain"] == "Garden"
        assert due[0]["status"] == "due"

    def test_week_sections_keep_shape(self, db_path, tmp_path):
        result = run_briefing(db_path, str(tmp_path / "out"))
        week = section(result.stdout, "This Week (next 7 days)").strip()
        # the section prints two JSON arrays back to back (activities, steps)
        decoder = json.JSONDecoder()
        acts, idx = decoder.raw_decode(week)
        steps, _ = decoder.raw_decode(week[idx:].strip())
        assert [a["activity"] for a in acts] == ["Sow Radish"]
        assert acts[0]["status"] == "watching"
        assert [s["step"] for s in steps] == ["Rake bed"]

    def test_briefing_has_no_inline_due_sql(self):
        with open(BRIEFING_SCRIPT) as f:
            src = f.read()
        assert "JOIN activities a ON s.activity_id" not in src
        assert "s.due_date <=" not in src
        assert "get_actionable_items" in src and "get_open_activities" in src


class TestNudgeUsesViews:
    def test_nudge_has_no_inline_due_sql(self):
        import evening_nudge
        src = inspect.getsource(evening_nudge.build_nudge)
        assert "SELECT" not in src
        assert "get_actionable_items" in src and "get_open_activities" in src

    def test_nudge_and_briefing_agree_on_due_now(self, db_path, tmp_path):
        import evening_nudge
        from plansync import engine
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        msg = evening_nudge.build_nudge(conn, TODAY.isoformat())
        conn.close()
        result = run_briefing(db_path, str(tmp_path / "out"))
        due = json.loads(section(result.stdout, "Due Today or Overdue"))
        assert "Water in" in msg
        assert [d["step"] for d in due] == ["Water in"]
