"""Tests for the deterministic morning briefing."""

import sqlite3
from datetime import date, timedelta
from unittest import mock

from sync import morning_briefing
from plansync import engine


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    import os
    schema = open(os.path.join(os.path.dirname(__file__), "..", "schema.sql")).read()
    conn.executescript(schema)
    conn.execute(
        "INSERT INTO domains (id, name, location) VALUES (?, ?, ?)",
        ("d1", "Yard", "Nashville, TN"),
    )
    conn.execute(
        "INSERT INTO domains (id, name, location) VALUES (?, ?, ?)",
        ("d2", "Hunting", "Nashville, TN"),
    )
    conn.commit()
    return conn


def _add_activity(conn, aid, domain_id, name, status="active", group_name=None,
                  trigger_date=None, trigger_type="calendar"):
    conn.execute(
        """INSERT INTO activities (id, domain_id, name, status, group_name,
           trigger_date, trigger_type, trigger_def)
           VALUES (?, ?, ?, ?, ?, ?, ?, '{}')""",
        (aid, domain_id, name, status, group_name, trigger_date, trigger_type),
    )


def _add_step(conn, sid, activity_id, name, due_date, status="pending",
              step_type="prep", lead_days=0):
    conn.execute(
        """INSERT INTO steps (id, activity_id, name, due_date, status,
           step_type, lead_days)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sid, activity_id, name, due_date, status, step_type, lead_days),
    )


class TestShortDate:
    def test_formats_correctly(self):
        assert morning_briefing._short_date("2026-08-05") == "Aug 5"
        assert morning_briefing._short_date("2026-12-25") == "Dec 25"
        assert morning_briefing._short_date("2026-01-01") == "Jan 1"


class TestSectionToday:
    def test_no_items_returns_none(self):
        conn = _setup_db()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            assert morning_briefing._section_today(conn) is None

    def test_shows_only_today_items(self):
        conn = _setup_db()
        _add_activity(conn, "a1", "d1", "Mow Lawn", group_name="Turf")
        _add_step(conn, "s1", "a1", "Sharpen blades", "2026-08-21")
        _add_step(conn, "s2", "a1", "Fill gas", "2026-08-20")  # overdue
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing._section_today(conn)
        assert result is not None
        assert "Today (1)" in result
        assert "Sharpen blades" in result
        assert "Fill gas" not in result

    def test_format_activity_colon_step(self):
        conn = _setup_db()
        _add_activity(conn, "a1", "d1", "Mow Lawn")
        _add_step(conn, "s1", "a1", "Sharpen blades", "2026-08-21")
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing._section_today(conn)
        assert "Mow Lawn: Sharpen blades" in result
        assert "Yard" not in result  # no domain prefix


class TestSectionOverdue:
    def test_no_overdue_returns_none(self):
        conn = _setup_db()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            assert morning_briefing._section_overdue(conn) is None

    def test_single_step_shows_name(self):
        conn = _setup_db()
        _add_activity(conn, "a1", "d1", "Mow Lawn")
        _add_step(conn, "s1", "a1", "Sharpen blades", "2026-08-15")
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing._section_overdue(conn)
        assert "Overdue (1)" in result
        assert "Mow Lawn: Sharpen blades" in result
        assert "due Aug 15" in result

    def test_multiple_steps_same_activity_bundled(self):
        conn = _setup_db()
        _add_activity(conn, "a1", "d1", "Armyworm Scouting")
        _add_step(conn, "s1", "a1", "Buy bifenthrin", "2026-08-08")
        _add_step(conn, "s2", "a1", "Soap-flush #1", "2026-08-15")
        _add_step(conn, "s3", "a1", "Soap-flush #2", "2026-08-18")
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing._section_overdue(conn)
        assert "Overdue (3)" in result
        assert "Armyworm Scouting: 3 steps" in result
        assert "due Aug 8" in result  # earliest date
        # Should be ONE line, not three
        assert result.count("Armyworm Scouting") == 1

    def test_cap_at_max_overdue(self):
        conn = _setup_db()
        for i in range(7):
            aid = f"a{i}"
            _add_activity(conn, aid, "d1", f"Task {i}")
            _add_step(conn, f"s{i}", aid, f"Step {i}", f"2026-08-{10+i:02d}")
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing._section_overdue(conn)
        assert "Overdue (7)" in result
        assert "…and 2 more" in result

    def test_overdue_excludes_today(self):
        conn = _setup_db()
        _add_activity(conn, "a1", "d1", "Mow Lawn")
        _add_step(conn, "s1", "a1", "Today step", "2026-08-21")  # due today
        _add_step(conn, "s2", "a1", "Old step", "2026-08-15")  # overdue
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing._section_overdue(conn)
        assert "Today step" not in result
        assert "Old step" in result


class TestSectionWeek:
    def test_shorter_format(self):
        conn = _setup_db()
        _add_activity(conn, "a1", "d1", "Mow Lawn", status="watching",
                      trigger_date="2026-08-25")
        _add_step(conn, "s1", "a1", "Sharpen blades", "2026-08-24")
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            with mock.patch.object(morning_briefing, "WEEK_CUTOFF", "2026-08-28"):
                result = morning_briefing._section_week(conn)
        assert result is not None
        assert "Aug 24" in result
        assert "2026" not in result  # no ISO dates
        assert "Yard —" not in result  # no domain prefix on lines


class TestSectionConditions:
    def test_shorter_format(self):
        conn = _setup_db()
        tdef = json.dumps({
            "type": "condition",
            "all": [{"metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 3}],
        })
        conn.execute(
            """INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("a1", "d1", "Overseed Bermuda", "watching", "condition", tdef),
        )
        conn.commit()
        result = morning_briefing._section_conditions(conn)
        assert result is not None
        assert "Overseed Bermuda [watching]" in result
        assert "Yard —" not in result  # no domain prefix


class TestBuildBriefing:
    def test_all_quiet(self):
        conn = _setup_db()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing.build_briefing(conn)
        assert "All quiet" in result

    def test_sections_ordered(self):
        conn = _setup_db()
        _add_activity(conn, "a1", "d1", "Mow Lawn")
        _add_step(conn, "s1", "a1", "Today step", "2026-08-21")
        _add_step(conn, "s2", "a1", "Old step", "2026-08-15")
        conn.commit()
        with mock.patch.object(morning_briefing, "TODAY", "2026-08-21"):
            result = morning_briefing.build_briefing(conn)
        today_pos = result.index("**Today")
        overdue_pos = result.index("**Overdue")
        assert today_pos < overdue_pos


import json
