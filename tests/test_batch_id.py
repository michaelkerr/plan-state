#!/usr/bin/env python3
"""Step 34: batch_id on activity_log groups cascaded side effects for undo."""

import os
import sqlite3
import subprocess
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from plansync.engine import log_change

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
MIGRATE_SCRIPT = os.path.join(ROOT, "scripts", "migrate-batch-id.py")

# activity_log DDL as it stood before Step 34 (no batch_id column) -- the
# migration must upgrade a live DB that was created from this shape.
PRE_34_ACTIVITY_LOG = """
CREATE TABLE activity_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
  item_type       TEXT NOT NULL CHECK(item_type IN ('domain','activity','step','condition')),
  item_id         TEXT NOT NULL,
  action          TEXT NOT NULL CHECK(action IN ('status_change','date_cascade','trigger_fire','manual_update','created','observation')),
  old_value       JSON,
  new_value       JSON,
  source          TEXT NOT NULL CHECK(source IN ('cron','hermes','claude','human'))
);
"""


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    yield conn
    conn.close()


def columns(conn, table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


class TestSchema:
    def test_schema_has_batch_id_column(self, db):
        assert "batch_id" in columns(db, "activity_log")


class TestLogChange:
    def test_log_change_with_batch_id_stores_it(self, db):
        batch = uuid.uuid4().hex[:12]
        log_change(db, "activity", "a1", "status_change", "watching", "active",
                   source="cron", batch_id=batch)
        row = db.execute("SELECT batch_id FROM activity_log").fetchone()
        assert row["batch_id"] == batch

    def test_log_change_without_batch_id_stores_null(self, db):
        log_change(db, "activity", "a1", "status_change", "watching", "active", source="cron")
        row = db.execute("SELECT batch_id FROM activity_log").fetchone()
        assert row["batch_id"] is None

    def test_batch_id_groups_multiple_entries(self, db):
        batch = uuid.uuid4().hex[:12]
        log_change(db, "activity", "a1", "status_change", "active", "completed",
                   source="hermes", batch_id=batch)
        log_change(db, "step", "s1", "status_change", "pending", "completed",
                   source="hermes", batch_id=batch)
        log_change(db, "step", "s2", "status_change", "due", "completed",
                   source="hermes", batch_id=batch)
        log_change(db, "activity", "a2", "status_change", "watching", "active", source="hermes")
        rows = db.execute(
            "SELECT item_type, item_id FROM activity_log WHERE batch_id=? ORDER BY id",
            (batch,),
        ).fetchall()
        assert [(r["item_type"], r["item_id"]) for r in rows] == [
            ("activity", "a1"), ("step", "s1"), ("step", "s2"),
        ]


class TestMigration:
    def make_pre_34_db(self, tmp_path):
        path = str(tmp_path / "live.db")
        conn = sqlite3.connect(path)
        with open(SCHEMA_PATH) as f:
            schema = f.read()
        conn.executescript(schema)
        # Rebuild activity_log at its pre-Step-34 shape
        conn.executescript("DROP TABLE activity_log;" + PRE_34_ACTIVITY_LOG)
        conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','D','X')")
        conn.execute(
            "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source) "
            "VALUES ('domain','d1','created',NULL,'{}','hermes')"
        )
        conn.commit()
        conn.close()
        return path

    def run_migration(self, db_path):
        return subprocess.run(
            [sys.executable, MIGRATE_SCRIPT],
            env={**os.environ, "PLANSYNC_DB": db_path},
            capture_output=True, text=True,
        )

    def test_migration_adds_column_and_preserves_rows(self, tmp_path):
        path = self.make_pre_34_db(tmp_path)
        result = self.run_migration(path)
        assert result.returncode == 0, result.stderr
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        assert "batch_id" in columns(conn, "activity_log")
        rows = conn.execute("SELECT * FROM activity_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["batch_id"] is None  # pre-existing entries stay NULL
        conn.close()

    def test_migration_is_idempotent(self, tmp_path):
        path = self.make_pre_34_db(tmp_path)
        assert self.run_migration(path).returncode == 0
        second = self.run_migration(path)
        assert second.returncode == 0, second.stderr
        assert "already" in (second.stdout + second.stderr).lower()

    def test_batch_id_queryable_after_migration(self, tmp_path):
        path = self.make_pre_34_db(tmp_path)
        assert self.run_migration(path).returncode == 0
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        batch = uuid.uuid4().hex[:12]
        log_change(conn, "activity", "a1", "status_change", "watching", "active",
                   source="claude", batch_id=batch)
        rows = conn.execute("SELECT * FROM activity_log WHERE batch_id=?", (batch,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["item_id"] == "a1"
        conn.close()
