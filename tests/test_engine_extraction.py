#!/usr/bin/env python3
"""Step 28: shared engine module -- no duplicated domain logic.

cascade/trigger-date/log/db logic lives only in plansync/engine.py;
server.py and daily_sync.py import it instead of keeping local copies.
"""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")

EXTRACTED = ["get_db", "log_change", "cascade_step_dates", "compute_trigger_date", "row_to_dict"]


def source_of(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


class TestNoLocalDefinitions:
    @pytest.mark.parametrize("path", [("mcp-server", "server.py"), ("sync", "daily_sync.py"), ("sync", "evening_nudge.py")])
    def test_no_local_copies_of_extracted_functions(self, path):
        src = source_of(*path)
        for name in EXTRACTED:
            assert f"def {name}(" not in src, f"{'/'.join(path)} still defines {name} locally"

    def test_no_local_cascade_arithmetic_in_daily_sync(self):
        # the old _cascade_steps carried its own prep/follow-up date math;
        # any surviving wrapper must delegate to the engine
        src = source_of("sync", "daily_sync.py")
        if "_cascade_steps" in src:
            assert "engine.cascade_step_dates" in src or "cascade_step_dates(" in src
            assert "timedelta(days=s[" not in src

    def test_engine_importable_without_mcp(self):
        import plansync.engine  # noqa: F401
        assert "mcp" not in sys.modules or not plansync.engine.__file__.startswith("mcp")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("PLANSYNC_DB", path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id,name,location) VALUES ('d1','D','X')")
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,trigger_type,trigger_date,status) "
        "VALUES ('a1','d1','Act','calendar','2027-03-10','watching')"
    )
    conn.execute(
        "INSERT INTO steps (id,activity_id,name,step_type,lead_days,status) VALUES ('s1','a1','Prep it','prep',7,'pending')"
    )
    conn.execute(
        "INSERT INTO steps (id,activity_id,name,step_type,lead_days,status) VALUES ('s2','a1','Follow up','follow_up',3,'pending')"
    )
    conn.commit()
    yield conn
    conn.close()


class TestEngineBehavior:
    def test_cascade_computes_prep_and_follow_up(self, db):
        from plansync import engine
        engine.cascade_step_dates(db, "a1", "2027-03-10")
        dues = {r["id"]: r["due_date"] for r in db.execute("SELECT id, due_date FROM steps")}
        assert dues == {"s1": "2027-03-03", "s2": "2027-03-13"}

    def test_cascade_logs_with_source(self, db):
        from plansync import engine
        engine.cascade_step_dates(db, "a1", "2027-03-10", source="cron")
        sources = {r["source"] for r in db.execute("SELECT source FROM activity_log")}
        assert sources == {"cron"}

    def test_cascade_on_change_callback(self, db):
        from plansync import engine
        seen = []
        engine.cascade_step_dates(
            db, "a1", "2027-03-10",
            on_change=lambda step, old, new: seen.append((step["name"], old, new)),
        )
        assert ("Prep it", None, "2027-03-03") in seen
        assert ("Follow up", None, "2027-03-13") in seen

    def test_cascade_skips_completed_steps(self, db):
        from plansync import engine
        db.execute("UPDATE steps SET status='completed' WHERE id='s1'")
        engine.cascade_step_dates(db, "a1", "2027-03-10")
        assert db.execute("SELECT due_date FROM steps WHERE id='s1'").fetchone()["due_date"] is None

    def test_cascade_none_trigger_date_is_noop(self, db):
        from plansync import engine
        engine.cascade_step_dates(db, "a1", None)
        assert db.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 0

    def test_compute_trigger_date(self):
        from plansync import engine
        assert engine.compute_trigger_date({"type": "calendar", "date": "2027-04-01"}) == "2027-04-01"
        assert engine.compute_trigger_date(json.dumps({"type": "calendar", "date": "2027-04-01"})) == "2027-04-01"
        assert engine.compute_trigger_date({"type": "condition", "conditions": []}) is None
        assert engine.compute_trigger_date(
            {"type": "compound", "operator": "AND", "conditions": [
                {"type": "condition", "metric": "daily_high", "operator": "<=", "value": 85},
                {"type": "calendar", "after": "2027-09-01"},
            ]}
        ) == "2027-09-01"
        assert engine.compute_trigger_date(None) is None

    def test_get_db_reads_env_at_call_time(self, db, tmp_path, monkeypatch):
        from plansync import engine
        other = str(tmp_path / "other.db")
        conn = sqlite3.connect(other)
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        conn.close()
        monkeypatch.setenv("PLANSYNC_DB", other)
        conn = engine.get_db()
        try:
            assert conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0] == 0
        finally:
            conn.close()

    def test_log_change_env_default_source(self, db, monkeypatch):
        from plansync import engine
        monkeypatch.setenv("PLANSYNC_CLIENT", "claude")
        engine.log_change(db, "domain", "d1", "created", None, {"name": "D"})
        assert db.execute("SELECT source FROM activity_log").fetchone()["source"] == "claude"
