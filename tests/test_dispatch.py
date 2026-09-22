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

    def test_invalid_transition(self, conn):
        from dispatch.store import insert_item, transition
        item_id = insert_item(conn, "garden", "X",
                              {"type": "calendar", "date": "2026-10-01"})
        conn.commit()
        with pytest.raises(ValueError, match="Cannot complete"):
            transition(conn, item_id, "complete")

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
