#!/usr/bin/env python3
"""Step 25: migrate-db.py rebuilds the live DB against the current schema.

The source fixture reproduces the LIVE database's actual pre-migration shape:
dead columns still present (recurrence, steps.condition, soil_temp), the
orphan todoist_sync table, 'deferred' in the status enum, and hand-authored
conditions rows. The migrated copy must match the current schema.sql exactly,
with row counts preserved and conditions re-derived at parity.
"""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
MIGRATE = os.path.join(ROOT, "scripts", "migrate-db.py")

OLD_SCHEMA = """
CREATE TABLE domains (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT, notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE activities (
  id TEXT PRIMARY KEY, domain_id TEXT NOT NULL REFERENCES domains(id),
  name TEXT NOT NULL, description TEXT, group_name TEXT,
  status TEXT DEFAULT 'watching' CHECK(status IN ('watching','preparing','active','completed','skipped','deferred')),
  trigger_type TEXT CHECK(trigger_type IN ('calendar','condition','dependency','compound')),
  trigger_def JSON, trigger_date DATE, trigger_fired DATETIME, completed_at DATETIME,
  recurrence JSON, sort_order INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE steps (
  id TEXT PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES activities(id),
  name TEXT NOT NULL, description TEXT,
  step_type TEXT NOT NULL CHECK(step_type IN ('prep','follow_up')),
  lead_days INTEGER NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'pending' CHECK(status IN ('pending','due','completed','skipped')),
  due_date DATE, completed_at DATETIME, condition JSON, sort_order INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE conditions (
  id TEXT PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES activities(id),
  condition_type TEXT NOT NULL CHECK(condition_type IN ('temperature','weather_event','calendar','dependency')),
  definition JSON NOT NULL, current_value REAL, is_met BOOLEAN DEFAULT 0, last_checked DATETIME
);
CREATE TABLE weather_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, location TEXT NOT NULL,
  recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  temp_high REAL, temp_low REAL, soil_temp REAL, conditions TEXT, precipitation REAL, forecast_json JSON
);
CREATE TABLE todoist_sync (
  id TEXT PRIMARY KEY, item_type TEXT, item_id TEXT, todoist_id TEXT, status TEXT
);
CREATE TABLE activity_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
  item_type TEXT NOT NULL CHECK(item_type IN ('domain','activity','step','condition')),
  item_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK(action IN ('status_change','date_cascade','trigger_fire','manual_update','created','observation')),
  old_value JSON, new_value JSON,
  source TEXT NOT NULL CHECK(source IN ('cron','hermes','claude','human'))
);
"""

COMPOUND_TDEF = {
    "type": "compound", "operator": "AND",
    "conditions": [
        {"type": "calendar", "after": "2026-09-05"},
        {"type": "condition", "all": [
            {"metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 3}]},
    ],
}


@pytest.fixture
def source_db(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO domains (id,name,location) VALUES ('d1','Yard','Murfreesboro,TN,US')")
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,status,trigger_type,trigger_def,trigger_date,recurrence) "
        "VALUES ('a1','d1','Compound Act','watching','compound',?,'2026-09-05','{\"type\": \"annual\"}')",
        (json.dumps(COMPOUND_TDEF),),
    )
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,status,trigger_type,trigger_def,trigger_date) "
        "VALUES ('a2','d1','Deferred Act','deferred','calendar','{\"type\": \"calendar\", \"date\": \"2026-08-01\"}','2026-08-01')"
    )
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,status,trigger_type,trigger_def) "
        "VALUES ('a3','d1','Done Act','completed','calendar','{\"type\": \"calendar\", \"date\": \"2026-06-01\"}')"
    )
    conn.execute(
        "INSERT INTO steps (id,activity_id,name,step_type,lead_days,due_date,condition) "
        "VALUES ('s1','a1','Prep','prep',5,'2026-08-31','{\"dead\": true}')"
    )
    conn.execute(
        "INSERT INTO steps (id,activity_id,name,step_type,lead_days,status) "
        "VALUES ('s2','a3','Old follow','follow_up',2,'completed')"
    )
    # hand-authored condition row matching the compound leaf, with live eval state
    conn.execute(
        "INSERT INTO conditions (id,activity_id,condition_type,definition,current_value,is_met,last_checked) "
        "VALUES ('c1','a1','temperature',?,88.1,0,'2026-07-20T11:00:00')",
        (json.dumps({"metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 3}),),
    )
    conn.execute(
        "INSERT INTO weather_log (location,recorded_at,temp_high,temp_low,soil_temp,conditions,precipitation) "
        "VALUES ('Murfreesboro,TN,US','2026-07-19 11:00:00',95.0,72.0,NULL,'Clear',0.0)"
    )
    conn.execute(
        "INSERT INTO weather_log (location,recorded_at,temp_high,temp_low,soil_temp,conditions,precipitation) "
        "VALUES ('Murfreesboro,TN,US','2026-07-20 11:00:00',97.0,74.0,NULL,'Clouds',0.1)"
    )
    conn.execute("INSERT INTO todoist_sync (id,item_type,item_id,todoist_id,status) VALUES ('t1','activity','a1','999','synced')")
    conn.execute(
        "INSERT INTO activity_log (item_type,item_id,action,old_value,new_value,source) "
        "VALUES ('activity','a1','created',NULL,'{}','hermes')"
    )
    conn.execute(
        "INSERT INTO activity_log (item_type,item_id,action,old_value,new_value,source) "
        "VALUES ('activity','a1','trigger_fire','{}','{}','cron')"
    )
    conn.commit()
    conn.close()
    return path


def run_migration(source, dest):
    return subprocess.run(
        [sys.executable, MIGRATE, "--source", source, "--dest", dest],
        capture_output=True, text=True,
    )


@pytest.fixture
def migrated(source_db, tmp_path):
    dest = str(tmp_path / "new" / "plansync.db")
    result = run_migration(source_db, dest)
    assert result.returncode == 0, result.stderr + result.stdout
    conn = sqlite3.connect(dest)
    conn.row_factory = sqlite3.Row
    yield conn, result
    conn.close()


class TestMigration:
    def test_row_counts_preserved(self, migrated):
        conn, _ = migrated
        assert conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM conditions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM weather_log").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 2

    def test_dead_surface_gone(self, migrated):
        conn, _ = migrated
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "todoist_sync" not in tables
        assert "recurrence" not in {r["name"] for r in conn.execute("PRAGMA table_info(activities)")}
        assert "condition" not in {r["name"] for r in conn.execute("PRAGMA table_info(steps)")}
        assert "soil_temp" not in {r["name"] for r in conn.execute("PRAGMA table_info(weather_log)")}

    def test_deferred_remapped_to_watching(self, migrated):
        conn, _ = migrated
        row = conn.execute("SELECT status FROM activities WHERE id='a2'").fetchone()
        assert row["status"] == "watching"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE activities SET status='deferred' WHERE id='a2'")

    def test_conditions_rederived_with_state_carried(self, migrated):
        conn, _ = migrated
        rows = conn.execute("SELECT * FROM conditions WHERE activity_id='a1'").fetchall()
        assert len(rows) == 1
        r = rows[0]
        assert r["condition_type"] == "temperature"
        assert json.loads(r["definition"]) == {
            "metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 3}
        assert r["current_value"] == 88.1
        assert r["last_checked"] == "2026-07-20T11:00:00"

    def test_weather_date_populated_and_unique(self, migrated):
        conn, _ = migrated
        rows = conn.execute("SELECT location, weather_date FROM weather_log ORDER BY weather_date").fetchall()
        # 11:00 UTC = 06:00 CDT -> local day matches the UTC date here
        assert [r["weather_date"] for r in rows] == ["2026-07-19", "2026-07-20"]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO weather_log (location, weather_date, temp_high, temp_low) "
                "VALUES ('Murfreesboro,TN,US','2026-07-20',90,70)"
            )

    def test_wal_mode_enabled(self, migrated):
        conn, _ = migrated
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

    def test_integrity_and_fk_clean(self, migrated):
        conn, _ = migrated
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    def test_refuses_existing_dest(self, source_db, tmp_path):
        dest = str(tmp_path / "exists.db")
        open(dest, "w").write("stub")
        result = run_migration(source_db, dest)
        assert result.returncode != 0
        assert "exists" in (result.stderr + result.stdout).lower()

    def test_fails_on_conditions_parity_mismatch(self, source_db, tmp_path):
        # a hand-authored row that does NOT match trigger_def leaves must abort
        conn = sqlite3.connect(source_db)
        conn.execute(
            "INSERT INTO conditions (id,activity_id,condition_type,definition) VALUES ('c9','a1','temperature',?)",
            (json.dumps({"metric": "daily_low", "operator": ">=", "value": 40}),),
        )
        conn.commit()
        conn.close()
        dest = str(tmp_path / "mismatch" / "plansync.db")
        result = run_migration(source_db, dest)
        assert result.returncode != 0
        assert "parity" in (result.stderr + result.stdout).lower()
        assert not os.path.exists(dest)


class TestPipelineAgainstMigratedDb:
    def test_sync_pipeline_runs_clean(self, migrated, tmp_path, monkeypatch):
        conn, result = migrated
        sys.path.insert(0, os.path.join(ROOT, "sync"))
        import sync_pipeline
        summary = sync_pipeline.SyncSummary()
        sync_pipeline.evaluate_conditions(conn, summary)
        sync_pipeline.evaluate_triggers(conn, summary)
        sync_pipeline.reestimate_dates(conn, summary)
        sync_pipeline.check_overdue(conn, summary)
        conn.commit()
        assert summary.errors == []

    def test_new_upsert_one_row_per_day(self, migrated):
        conn, _ = migrated
        sys.path.insert(0, os.path.join(ROOT, "sync"))
        import sync_pipeline
        sync_pipeline.upsert_weather_row(conn, "Murfreesboro,TN,US", 91.0, 71.0, "Clear", 0.0, "{}")
        sync_pipeline.upsert_weather_row(conn, "Murfreesboro,TN,US", 93.0, 70.0, "Clouds", 0.0, "{}")
        conn.commit()
        rows = conn.execute(
            "SELECT temp_high FROM weather_log WHERE location='Murfreesboro,TN,US' AND weather_date=?",
            (sync_pipeline.TODAY.isoformat(),),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["temp_high"] == 93.0
