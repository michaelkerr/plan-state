#!/usr/bin/env python3
"""Step 35: state machines as transition tables + cascade reactor in engine.py."""

import json
import os
import sqlite3
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from plansync import engine
from plansync.engine import transition, react, new_batch_id

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
TODAY = date.today()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','Test','X')")
    yield conn
    conn.close()


def add_activity(db, aid, status="watching", trigger_type="calendar",
                 trigger_def=None, trigger_date=None, name=None):
    tdef = json.dumps(trigger_def) if trigger_def else json.dumps(
        {"type": "calendar", "date": trigger_date or "2027-01-01"})
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
        "VALUES (?,?,?,?,?,?,?)",
        (aid, "d1", name or aid, status, trigger_type, tdef, trigger_date),
    )


def add_step(db, sid, aid, step_type="prep", status="pending", lead_days=0,
             due_date=None, name=None):
    db.execute(
        "INSERT INTO steps (id, activity_id, name, step_type, lead_days, status, due_date) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, aid, name or sid, step_type, lead_days, status, due_date),
    )


def status_of(db, table, eid):
    return db.execute(f"SELECT status FROM {table} WHERE id=?", (eid,)).fetchone()["status"]


def row(db, table, eid):
    return db.execute(f"SELECT * FROM {table} WHERE id=?", (eid,)).fetchone()


class TestActivityTransitions:
    def test_complete_from_active(self, db):
        add_activity(db, "a1", status="active")
        events = transition(db, "activity", "a1", "complete")
        assert status_of(db, "activities", "a1") == "completed"
        assert row(db, "activities", "a1")["completed_at"] is not None
        assert events == [{"type": "activity_completed", "activity_id": "a1"}]

    def test_complete_from_preparing(self, db):
        add_activity(db, "a1", status="preparing")
        transition(db, "activity", "a1", "complete")
        assert status_of(db, "activities", "a1") == "completed"

    def test_complete_from_watching_rejected(self, db):
        add_activity(db, "a1", status="watching")
        with pytest.raises(ValueError) as e:
            transition(db, "activity", "a1", "complete")
        assert "watching" in str(e.value) and "complete" in str(e.value)
        assert status_of(db, "activities", "a1") == "watching"

    def test_complete_twice_rejected(self, db):
        add_activity(db, "a1", status="active")
        transition(db, "activity", "a1", "complete")
        with pytest.raises(ValueError):
            transition(db, "activity", "a1", "complete")

    def test_trigger_fire_without_prep_goes_active(self, db):
        add_activity(db, "a1", status="watching")
        transition(db, "activity", "a1", "trigger_fire")
        assert status_of(db, "activities", "a1") == "active"

    def test_trigger_fire_with_prep_goes_preparing(self, db):
        add_activity(db, "a1", status="watching")
        add_step(db, "s1", "a1", step_type="prep")
        transition(db, "activity", "a1", "trigger_fire")
        assert status_of(db, "activities", "a1") == "preparing"

    def test_activate_from_preparing(self, db):
        add_activity(db, "a1", status="preparing")
        transition(db, "activity", "a1", "activate")
        assert status_of(db, "activities", "a1") == "active"

    def test_defer_returns_to_watching(self, db):
        add_activity(db, "a1", status="active")
        transition(db, "activity", "a1", "defer")
        assert status_of(db, "activities", "a1") == "watching"

    def test_defer_while_watching_is_valid_noop(self, db):
        add_activity(db, "a1", status="watching")
        events = transition(db, "activity", "a1", "defer")
        assert status_of(db, "activities", "a1") == "watching"
        assert events == []
        # No status actually changed, so no status_change log entry
        n = db.execute("SELECT COUNT(*) c FROM activity_log").fetchone()["c"]
        assert n == 0

    def test_skip(self, db):
        add_activity(db, "a1", status="watching")
        transition(db, "activity", "a1", "skip")
        assert status_of(db, "activities", "a1") == "skipped"

    def test_revert_restores_context_status(self, db):
        add_activity(db, "a1", status="active")
        transition(db, "activity", "a1", "complete")
        transition(db, "activity", "a1", "revert", {"to_status": "active"})
        a = row(db, "activities", "a1")
        assert a["status"] == "active"
        assert a["completed_at"] is None

    def test_revert_requires_to_status(self, db):
        add_activity(db, "a1", status="completed")
        with pytest.raises(ValueError):
            transition(db, "activity", "a1", "revert")

    def test_revert_rejects_invalid_to_status(self, db):
        add_activity(db, "a1", status="completed")
        with pytest.raises(ValueError):
            transition(db, "activity", "a1", "revert", {"to_status": "pending"})


class TestStepTransitions:
    def test_complete_from_pending(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="pending")
        transition(db, "step", "s1", "complete")
        s = row(db, "steps", "s1")
        assert s["status"] == "completed"
        assert s["completed_at"] is not None

    def test_complete_from_due(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="due")
        transition(db, "step", "s1", "complete")
        assert status_of(db, "steps", "s1") == "completed"

    def test_parent_complete_from_pending_and_due(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="pending")
        add_step(db, "s2", "a1", status="due")
        transition(db, "step", "s1", "parent_complete")
        transition(db, "step", "s2", "parent_complete")
        assert status_of(db, "steps", "s1") == "completed"
        assert status_of(db, "steps", "s2") == "completed"

    def test_promote_and_overdue_reach_due(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="pending")
        add_step(db, "s2", "a1", status="pending")
        transition(db, "step", "s1", "promote")
        transition(db, "step", "s2", "overdue")
        assert status_of(db, "steps", "s1") == "due"
        assert status_of(db, "steps", "s2") == "due"

    def test_overdue_on_due_step_rejected(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="due")
        with pytest.raises(ValueError):
            transition(db, "step", "s1", "overdue")

    def test_uncomplete_clears_timestamp(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="pending")
        transition(db, "step", "s1", "complete")
        transition(db, "step", "s1", "uncomplete")
        s = row(db, "steps", "s1")
        assert s["status"] == "pending"
        assert s["completed_at"] is None

    def test_complete_skipped_step_rejected(self, db):
        add_activity(db, "a1", status="active")
        add_step(db, "s1", "a1", status="skipped")
        with pytest.raises(ValueError):
            transition(db, "step", "s1", "complete")


class TestTransitionValidation:
    def test_unknown_entity_type(self, db):
        with pytest.raises(ValueError):
            transition(db, "domain", "d1", "complete")

    def test_missing_entity(self, db):
        with pytest.raises(ValueError):
            transition(db, "activity", "nope", "complete")

    def test_unknown_event(self, db):
        add_activity(db, "a1", status="active")
        with pytest.raises(ValueError):
            transition(db, "activity", "a1", "explode")

    def test_error_names_state_and_event(self, db):
        add_activity(db, "a1", status="skipped")
        with pytest.raises(ValueError) as e:
            transition(db, "activity", "a1", "complete")
        msg = str(e.value)
        assert "skipped" in msg and "complete" in msg


class TestTransitionLogging:
    def test_logs_status_change_with_batch_id(self, db):
        add_activity(db, "a1", status="active")
        batch = new_batch_id()
        transition(db, "activity", "a1", "complete", {"batch_id": batch, "source": "claude"})
        entry = db.execute("SELECT * FROM activity_log").fetchone()
        assert entry["action"] == "status_change"
        assert entry["batch_id"] == batch
        assert entry["source"] == "claude"
        assert json.loads(entry["old_value"]) == {"status": "active"}
        assert json.loads(entry["new_value"])["status"] == "completed"


class TestReact:
    def seed_completion_scene(self, db):
        """Active activity with mixed-status prep steps, follow-ups, and two
        dependency watchers (one with prep steps, one without)."""
        add_activity(db, "a1", status="active", name="Main")
        add_step(db, "p1", "a1", step_type="prep", status="pending")
        add_step(db, "p2", "a1", step_type="prep", status="due")
        add_step(db, "p3", "a1", step_type="prep", status="completed")
        add_step(db, "f1", "a1", step_type="follow_up", status="pending", lead_days=2)
        add_step(db, "f2", "a1", step_type="follow_up", status="pending", lead_days=5)
        add_activity(db, "dep1", status="watching", trigger_type="dependency",
                     trigger_def={"type": "dependency", "activity_id": "a1",
                                  "event": "completed", "offset_days": 3})
        add_step(db, "dp1", "dep1", step_type="prep", lead_days=1)
        add_activity(db, "dep2", status="watching", trigger_type="dependency",
                     trigger_def={"type": "dependency", "activity_id": "a1",
                                  "event": "completed"})
        add_activity(db, "other", status="watching", trigger_type="dependency",
                     trigger_def={"type": "dependency", "activity_id": "zzz",
                                  "event": "completed"})

    def complete_and_react(self, db):
        batch = new_batch_id()
        ctx = {"batch_id": batch, "source": "hermes"}
        events = transition(db, "activity", "a1", "complete", ctx)
        result = react(db, events, batch, source="hermes")
        return batch, result

    def test_prep_steps_pending_and_due_complete(self, db):
        self.seed_completion_scene(db)
        _, result = self.complete_and_react(db)
        assert status_of(db, "steps", "p1") == "completed"
        assert status_of(db, "steps", "p2") == "completed"
        assert {s["id"] for s in result["steps_completed"]} == {"p1", "p2"}

    def test_follow_ups_promoted_with_dates(self, db):
        self.seed_completion_scene(db)
        _, result = self.complete_and_react(db)
        f1, f2 = row(db, "steps", "f1"), row(db, "steps", "f2")
        assert f1["status"] == "due"
        assert f1["due_date"] == (TODAY + timedelta(days=2)).isoformat()
        assert f2["status"] == "due"
        assert f2["due_date"] == (TODAY + timedelta(days=5)).isoformat()
        assert {s["id"] for s in result["follow_ups_promoted"]} == {"f1", "f2"}

    def test_dependencies_fire_with_offset(self, db):
        self.seed_completion_scene(db)
        _, result = self.complete_and_react(db)
        dep1 = row(db, "activities", "dep1")
        assert dep1["status"] == "preparing"  # has a prep step
        assert dep1["trigger_date"] == (TODAY + timedelta(days=3)).isoformat()
        assert dep1["trigger_fired"] is not None
        dep2 = row(db, "activities", "dep2")
        assert dep2["status"] == "active"  # no prep steps
        assert dep2["trigger_date"] == TODAY.isoformat()
        assert status_of(db, "activities", "other") == "watching"
        assert {d["id"] for d in result["dependencies_fired"]} == {"dep1", "dep2"}

    def test_fired_dependency_steps_cascade(self, db):
        self.seed_completion_scene(db)
        self.complete_and_react(db)
        dp1 = row(db, "steps", "dp1")
        # prep with lead_days=1 lands one day before the fired trigger date
        assert dp1["due_date"] == (TODAY + timedelta(days=2)).isoformat()

    def test_cascade_shares_batch_id(self, db):
        self.seed_completion_scene(db)
        batch, _ = self.complete_and_react(db)
        rows = db.execute("SELECT item_type, item_id, batch_id FROM activity_log").fetchall()
        assert len(rows) > 1
        assert all(r["batch_id"] == batch for r in rows)
        logged = {(r["item_type"], r["item_id"]) for r in rows}
        assert ("activity", "a1") in logged
        assert ("step", "p1") in logged and ("step", "p2") in logged
        assert ("step", "f1") in logged and ("step", "f2") in logged
        assert ("activity", "dep1") in logged and ("activity", "dep2") in logged

    def test_completed_prep_untouched(self, db):
        self.seed_completion_scene(db)
        before = row(db, "steps", "p3")["completed_at"]
        self.complete_and_react(db)
        assert row(db, "steps", "p3")["completed_at"] == before

    def test_react_empty_events_is_noop(self, db):
        result = react(db, [], new_batch_id())
        assert result == {"steps_completed": [], "follow_ups_promoted": [],
                          "dependencies_fired": [], "steps_skipped": []}

    def test_no_raw_status_updates_needed(self, db):
        """The reactor path produces valid states end-to-end -- every touched
        entity lands in a state the transition tables allow."""
        self.seed_completion_scene(db)
        self.complete_and_react(db)
        for aid in ("a1", "dep1", "dep2", "other"):
            assert status_of(db, "activities", aid) in engine.ACTIVITY_STATUSES
        for sid in ("p1", "p2", "p3", "f1", "f2", "dp1"):
            assert status_of(db, "steps", sid) in engine.STEP_STATUSES
