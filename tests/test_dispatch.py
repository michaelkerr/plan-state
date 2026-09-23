"""Tests for dispatch store, transitions, eval, resolve, briefing, nudge, doctor."""

import json
import os
import pytest
from datetime import datetime

os.environ.setdefault("DISPATCH_DB", ":memory:")


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DISPATCH_DB", db_path)
    from dispatch.store import init_db
    init_db(db_path)
    return db_path


@pytest.fixture
def conn(db):
    from dispatch.store import connect
    with connect() as c:
        yield c


# --- Store basics ---

class TestStore:
    def test_insert_and_get(self, conn):
        from dispatch.store import insert_item, get_item
        item_id = insert_item(conn, "garden", "Plant tomatoes",
                              {"type": "calendar", "date": "2026-10-01"},
                              group="Tomatoes", source_ref="tomatoes")
        conn.commit()
        item = get_item(conn, item_id)
        assert item["name"] == "Plant tomatoes"
        assert item["domain"] == "garden"
        assert item["status"] == "watching"
        assert item["trigger_def"]["type"] == "calendar"
        assert item["group"] == "Tomatoes"

    def test_get_items_filter(self, conn):
        from dispatch.store import insert_item, get_items
        insert_item(conn, "garden", "A", {"type": "calendar", "date": "2026-10-01"})
        insert_item(conn, "lawn", "B", {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        all_items = get_items(conn)
        assert len(all_items) == 2
        garden_only = get_items(conn, domain="garden")
        assert len(garden_only) == 1
        assert garden_only[0]["domain"] == "garden"

    def test_get_open_items(self, conn):
        from dispatch.store import insert_item, get_open_items, transition
        a = insert_item(conn, "garden", "A", {"type": "calendar", "date": "2026-10-01"})
        b = insert_item(conn, "garden", "B", {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        transition(conn, a, "fire", due_date="2026-10-01")
        transition(conn, a, "complete")
        open_items = get_open_items(conn)
        assert len(open_items) == 1
        assert open_items[0]["id"] == b


# --- Transitions ---

class TestTransitions:
    def test_fire(self, conn):
        from dispatch.store import insert_item, transition, get_item
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        updated = transition(conn, item_id, "fire", due_date="2026-10-01")
        assert updated["status"] == "due"
        assert updated["due_date"] == "2026-10-01"

    def test_complete(self, conn):
        from dispatch.store import insert_item, transition
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        transition(conn, item_id, "fire", due_date="2026-10-01")
        updated = transition(conn, item_id, "complete", notes="all done")
        assert updated["status"] == "done"
        assert updated["completed_at"] is not None

    def test_complete_from_watching(self, conn):
        from dispatch.store import insert_item, transition, get_item
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        updated = transition(conn, item_id, "complete")
        assert updated["status"] == "done"
        assert get_item(conn, item_id)["status"] == "done"

    def test_skip(self, conn):
        from dispatch.store import insert_item, transition
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        updated = transition(conn, item_id, "skip")
        assert updated["status"] == "skipped"

    def test_defer(self, conn):
        from dispatch.store import insert_item, transition
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        transition(conn, item_id, "fire", due_date="2026-10-01")
        updated = transition(conn, item_id, "defer", new_date="2026-10-15")
        assert updated["status"] == "watching"
        assert updated["due_date"] is None

    def test_dependency_fires(self, conn):
        from dispatch.store import insert_item, transition, get_item
        a = insert_item(conn, "garden", "A",
                        {"type": "calendar", "date": "2026-10-01"})
        b = insert_item(conn, "garden", "B",
                        {"type": "after", "item_ref": a, "event": "completed"})
        conn.commit()
        transition(conn, a, "fire", due_date="2026-10-01")
        transition(conn, a, "complete")
        item_b = get_item(conn, b)
        assert item_b["status"] == "due"

    def test_dependency_offset_waits(self, conn):
        from dispatch.store import insert_item, transition, get_item
        a = insert_item(conn, "lawn", "Aerate",
                        {"type": "calendar", "date": "2026-09-05"})
        b = insert_item(conn, "lawn", "Fall nitrogen",
                        {"type": "after", "item_ref": a, "event": "completed",
                         "offset_days": 14})
        conn.commit()
        transition(conn, a, "fire", due_date="2026-09-05")
        transition(conn, a, "complete")
        assert get_item(conn, b)["status"] == "watching"

    def test_undo_complete(self, conn):
        from dispatch.store import insert_item, transition, new_id
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        transition(conn, item_id, "fire", due_date="2026-10-01")
        batch = new_id()
        transition(conn, item_id, "complete", batch_id=batch)
        updated = transition(conn, item_id, "undo")
        assert updated["status"] == "due"


# --- Resolve ---

class TestResolve:
    def test_code_match(self, conn):
        from dispatch.store import insert_item
        from dispatch.resolve import resolve
        insert_item(conn, "garden", "Tomatoes",
                    {"type": "calendar", "date": "2026-10-01"})
        insert_item(conn, "garden", "Peppers",
                    {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        matches, exact = resolve("G1")
        assert exact
        assert matches[0]["name"] == "Tomatoes"
        matches2, exact2 = resolve("G2")
        assert exact2
        assert matches2[0]["name"] == "Peppers"

    def test_name_match(self, conn):
        from dispatch.store import insert_item
        from dispatch.resolve import resolve
        insert_item(conn, "garden", "Plant tomatoes",
                    {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        matches, exact = resolve("tomatoes")
        assert exact
        assert matches[0]["name"] == "Plant tomatoes"

    def test_ambiguous(self, conn):
        from dispatch.store import insert_item
        from dispatch.resolve import resolve
        insert_item(conn, "garden", "Spray tomatoes",
                    {"type": "calendar", "date": "2026-10-01"})
        insert_item(conn, "garden", "Pick tomatoes",
                    {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        matches, exact = resolve("tomatoes")
        assert not exact
        assert len(matches) == 2

    def test_no_match(self, conn):
        from dispatch.resolve import resolve
        matches, exact = resolve("nonexistent")
        assert not matches


# --- Briefing & Nudge ---

class TestBriefingNudge:
    def test_empty_briefing(self, db):
        from dispatch.briefing import build_briefing
        assert build_briefing() == ""

    def test_briefing_with_due(self, conn, db):
        from dispatch.store import insert_item, transition
        from dispatch.briefing import build_briefing
        item_id = insert_item(conn, "garden", "Water plants",
                              {"type": "calendar", "date": "2026-09-21"})
        conn.commit()
        transition(conn, item_id, "fire", due_date="2026-09-21")
        text = build_briefing(today="2026-09-21")
        assert "Water plants" in text
        assert "Due today" in text

    def test_briefing_lists_each_item_once(self, conn, db):
        from dispatch.store import insert_item, transition
        from dispatch.briefing import build_briefing
        overdue_id = insert_item(conn, "hunting", "Deploy trail cameras",
                                 {"type": "calendar", "date": "2026-07-28"})
        today_id = insert_item(conn, "garden", "Direct sow roots",
                               {"type": "calendar", "date": "2026-09-23"})
        done_id = insert_item(conn, "lawn", "Spot spray",
                              {"type": "calendar", "date": "2026-09-22"})
        insert_item(conn, "garden", "Frost protection",
                    {"type": "calendar", "date": "2026-10-16"})
        conn.commit()
        transition(conn, overdue_id, "fire", due_date="2026-07-28")
        transition(conn, today_id, "fire", due_date="2026-09-23")
        transition(conn, done_id, "fire", due_date="2026-09-22")
        transition(conn, done_id, "complete")
        text = build_briefing(today="2026-09-23")
        due = self._section_body(text, "Due today")
        overdue = self._section_body(text, "Overdue")

        assert "Direct sow roots" in due
        assert "[G2]" in due
        assert "Deploy trail cameras" not in due
        assert "Deploy trail cameras" in overdue
        assert "[H1]" in overdue
        assert "Direct sow roots" not in overdue
        assert "Spot spray" not in text
        assert "Newly triggered" not in text
        assert "Quick close" not in text
        assert "Frost protection" not in text

    def test_watching_calendar_shows_in_this_week(self, conn, db):
        from dispatch.store import insert_item
        from dispatch.briefing import build_briefing
        insert_item(conn, "hunting", "Deer Archery Opener",
                    {"type": "calendar", "date": "2026-09-26"},
                    group="Deer")
        conn.commit()
        text = build_briefing(today="2026-09-23")
        week = self._section_body(text, "The next 7 days")
        assert "Deer Archery Opener" in week
        assert "Sep 26" in week
        assert "[H1]" in week

    def test_follow_up_shows_on_its_real_date(self, conn, db):
        from dispatch.store import insert_item, transition
        from dispatch.briefing import build_briefing
        parent = insert_item(conn, "lawn", "Aerate",
                             {"type": "calendar", "date": "2026-09-05"})
        insert_item(conn, "lawn", "Fall nitrogen soon",
                    {"type": "after", "item_ref": parent, "event": "completed",
                     "offset_days": 3})
        insert_item(conn, "lawn", "Fall nitrogen later",
                    {"type": "after", "item_ref": parent, "event": "completed",
                     "offset_days": 14})
        conn.commit()
        transition(conn, parent, "fire", due_date="2026-09-05")
        transition(conn, parent, "complete")
        conn.execute(
            "UPDATE items SET completed_at=? WHERE id=?",
            ("2026-09-23T15:00:00", parent),
        )
        conn.commit()
        text = build_briefing(today="2026-09-23")
        window = self._section_body(text, "The next 7 days")
        assert "Fall nitrogen soon" in window
        assert "Sep 26" in window
        assert "~" in window
        assert "**Due today**" not in text or "Fall nitrogen soon" not in self._section_body(text, "Due today")
        assert "Fall nitrogen later" not in text

    def test_conditions_lead_the_briefing(self, conn, db):
        from dispatch.store import insert_item, new_id, now_iso
        from dispatch.briefing import build_briefing
        item_id = insert_item(
            conn, "lawn", "Fall overseed",
            {"type": "condition", "rules": [{
                "metric": "daily_high", "operator": "<=",
                "value": 85, "sustained_days": 3,
            }]},
        )
        conn.execute(
            """INSERT INTO weather_log
               (id, location, weather_date, recorded_at,
                temp_current, temp_high, temp_low, conditions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), "Murfreesboro,TN,US", "2026-09-23", now_iso(),
             70, 78.01, 65.5, '["Clouds"]'),
        )
        conn.execute(
            """INSERT INTO conditions_cache
               (id, item_id, metric, operator, value, sustained_days,
                current_value, is_met)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), item_id, "daily_high", "<=", 85, 3, 78.01, 0),
        )
        conn.commit()
        text = build_briefing(today="2026-09-23")
        assert text.split("\n\n")[1].startswith("**Conditions**")
        assert "Location: Murfreesboro,TN,US" in text
        assert "Weather:" in text
        assert "Clouds" in text
        assert "daily_high <= 85° for 3 days: not met" in text

    def _section_body(self, text, title):
        marker = f"**{title}**"
        start = text.index(marker) + len(marker)
        rest = text[start:]
        nxt = rest.find("\n**")
        return rest if nxt < 0 else rest[:nxt]

    def test_empty_nudge(self, db):
        from dispatch.nudge import build_nudge
        assert build_nudge() == ""

    def test_nudge_with_due(self, conn, db):
        from dispatch.store import insert_item, transition
        from dispatch.nudge import build_nudge
        item_id = insert_item(conn, "garden", "Water plants",
                              {"type": "calendar", "date": "2026-09-21"})
        conn.commit()
        transition(conn, item_id, "fire", due_date="2026-09-21")
        text = build_nudge(today="2026-09-21")
        assert "Water plants" in text
        assert "done" in text.lower()

    def test_skip_tool(self, conn, db):
        from dispatch.store import insert_item, transition
        from dispatch.server import _skip
        item_id = insert_item(conn, "hunting", "Deploy trail cameras",
                              {"type": "calendar", "date": "2026-07-28"})
        conn.commit()
        transition(conn, item_id, "fire", due_date="2026-07-28")
        result = _skip({"query": "H1", "notes": "not this year"})
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["skipped"]["id"] == item_id
        assert body["skipped"]["status"] == "skipped"

    def test_nudge_codes_match_resolve(self, conn, db):
        from dispatch.store import insert_item, transition
        from dispatch.nudge import build_nudge
        from dispatch.resolve import resolve
        insert_item(conn, "hunting", "Season closeout",
                    {"type": "calendar", "date": "2027-01-11"},
                    sort_order=2)
        due_id = insert_item(conn, "hunting", "Deploy trail cameras",
                             {"type": "calendar", "date": "2026-07-28"},
                             sort_order=3)
        conn.commit()
        transition(conn, due_id, "fire", due_date="2026-07-28")
        text = build_nudge(today="2026-09-21")
        assert "[H2]" in text
        assert "[H1]" not in text
        matches, exact = resolve("H2")
        assert exact
        assert matches[0]["id"] == due_id

    def test_closed_item_keeps_its_code(self, conn, db):
        from dispatch.store import insert_item, transition
        from dispatch.resolve import resolve
        first = insert_item(conn, "garden", "Sow radish",
                            {"type": "calendar", "date": "2026-09-15"},
                            sort_order=2)
        second = insert_item(conn, "garden", "Transplant brassicas",
                             {"type": "calendar", "date": "2026-09-06"},
                             sort_order=5)
        conn.commit()
        transition(conn, first, "fire", due_date="2026-09-15")
        transition(conn, first, "complete")
        transition(conn, second, "fire", due_date="2026-09-06")
        done_match, done_exact = resolve("G1")
        assert done_exact
        assert done_match[0]["id"] == first
        assert done_match[0]["status"] == "done"
        still, exact = resolve("G2")
        assert exact
        assert still[0]["id"] == second
        assert still[0]["status"] == "due"


# --- Doctor ---

class TestDoctor:
    def test_doctor_runs(self, db):
        from dispatch.doctor import run_doctor
        output = run_doctor()
        assert "dispatch doctor" in output
        assert "DB exists" in output
        assert "ok" in output


# --- Event log ---

class TestEventLog:
    def test_events_logged(self, conn):
        from dispatch.store import insert_item, transition
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        transition(conn, item_id, "fire", due_date="2026-10-01")
        events = conn.execute(
            "SELECT * FROM event_log WHERE item_id=?", (item_id,)
        ).fetchall()
        assert len(events) >= 1
        types = [dict(e)["event_type"] for e in events]
        assert "item_fired" in types
