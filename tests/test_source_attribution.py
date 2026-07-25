#!/usr/bin/env python3
"""Step 27: activity_log source attribution follows PLANSYNC_CLIENT."""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, os.path.join(ROOT, "sync"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")

DOMAIN = {
    "name": "Attribution Test",
    "location": "Nashville,TN,US",
    "activities": [
        {
            "name": "Only Activity",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2027-03-01"},
        }
    ],
}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.close()
    return path


@pytest.fixture
def db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_db_path(db_path, monkeypatch):
    monkeypatch.setenv("PLANSYNC_DB", db_path)
    import server


def call_load_domain():
    import server
    conn = server.get_db()
    try:
        result = server._load_domain(conn, {"definition": DOMAIN})
        return json.loads(result[0].text)
    finally:
        conn.close()


def log_sources(db):
    return {r["source"] for r in db.execute("SELECT source FROM activity_log").fetchall()}


class TestSourceAttribution:
    def test_default_source_is_hermes(self, db, monkeypatch):
        monkeypatch.delenv("PLANSYNC_CLIENT", raising=False)
        result = call_load_domain()
        assert "error" not in result
        assert log_sources(db) == {"hermes"}

    def test_client_env_sets_source_claude(self, db, monkeypatch):
        monkeypatch.setenv("PLANSYNC_CLIENT", "claude")
        result = call_load_domain()
        assert "error" not in result
        assert log_sources(db) == {"claude"}

    def test_explicit_source_arg_wins_over_env(self, db, monkeypatch):
        # Callers that pass source explicitly (none today) must not be
        # silently rerouted by the env var.
        monkeypatch.setenv("PLANSYNC_CLIENT", "claude")
        import server
        conn = server.get_db()
        conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','D','X')")
        server.log_change(conn, "domain", "d1", "created", None, {"name": "D"}, source="human")
        conn.commit()
        conn.close()
        assert log_sources(db) == {"human"}

    def test_schema_accepts_all_four_sources(self, db):
        db.execute("INSERT INTO domains (id, name, location) VALUES ('d1','D','X')")
        for src in ("cron", "hermes", "claude", "human"):
            db.execute(
                "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source) "
                "VALUES ('domain','d1','created',NULL,NULL,?)",
                (src,),
            )
        db.commit()
        assert log_sources(db) == {"cron", "hermes", "claude", "human"}

    def test_schema_rejects_unknown_source(self, db):
        db.execute("INSERT INTO domains (id, name, location) VALUES ('d1','D','X')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source) "
                "VALUES ('domain','d1','created',NULL,NULL,'todoist')"
            )

    def test_cron_pipeline_still_logs_cron(self, db, monkeypatch):
        monkeypatch.setenv("PLANSYNC_CLIENT", "claude")  # must not affect the cron path
        import sync_pipeline
        db.execute("INSERT INTO domains (id, name, location) VALUES ('d1','D','X')")
        db.execute(
            "INSERT INTO activities (id,domain_id,name,trigger_type,trigger_def,trigger_date,status) "
            "VALUES ('a1','d1','Act','calendar','{\"type\": \"calendar\", \"date\": \"2026-01-01\"}','2026-01-01','watching')"
        )
        db.execute(
            "INSERT INTO steps (id,activity_id,name,step_type,lead_days,status) VALUES ('s1','a1','After','follow_up',2,'pending')"
        )
        db.commit()
        sync_pipeline.evaluate_triggers(db, sync_pipeline.SyncSummary())
        db.commit()
        assert len(log_sources(db)) > 0
        assert log_sources(db) == {"cron"}
