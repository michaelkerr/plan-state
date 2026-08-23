#!/usr/bin/env python3
"""Step 48: sync pipeline stages are independently callable with explicit
inputs and outputs; main() aggregates them into the summary."""

import json
import os
import sqlite3
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import sync_pipeline

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("PLANSYNC_DB", path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','G','Murfreesboro,TN,US')")
    conn.commit()
    yield conn
    conn.close()


def seed_watching_calendar(db, aid="a1", trigger_date=YESTERDAY):
    db.execute(
        "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
        "VALUES (?,?,?,?,'calendar',?,?)",
        (aid, "d1", aid, "watching",
         json.dumps({"type": "calendar", "date": trigger_date}), trigger_date))
    db.commit()


class TestStandaloneStages:
    def test_evaluate_triggers_returns_fired_without_summary(self, db):
        seed_watching_calendar(db)
        result = sync_pipeline.evaluate_triggers(db)
        db.commit()
        assert [f["name"] for f in result["fired"]] == ["a1"]
        assert db.execute("SELECT status FROM activities WHERE id='a1'").fetchone()["status"] == "active"

    def test_evaluate_conditions_works_from_seeded_weather(self, db):
        # no pull_weather call -- conditions evaluate from existing weather rows
        db.execute(
            "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def) "
            "VALUES ('a1','d1','A','watching','condition',?)",
            (json.dumps({"type": "condition",
                         "all": [{"metric": "daily_high", "operator": ">=", "value": 70}]}),))
        db.execute(
            "INSERT INTO conditions (id, activity_id, condition_type, definition) VALUES "
            "('c1','a1','temperature',?)",
            (json.dumps({"metric": "daily_high", "operator": ">=", "value": 70}),))
        db.execute(
            "INSERT INTO weather_log (location, weather_date, temp_high, temp_low) "
            "VALUES ('Murfreesboro,TN,US', ?, 80, 60)", (TODAY.isoformat(),))
        db.commit()
        result = sync_pipeline.evaluate_conditions(db)
        db.commit()
        assert result["evaluated"] == 1
        assert result["met"] == 1
        assert db.execute("SELECT is_met FROM conditions WHERE id='c1'").fetchone()["is_met"] == 1

    def test_check_overdue_returns_list_without_summary(self, db):
        db.execute("INSERT INTO activities (id, domain_id, name, status) VALUES ('a1','d1','A','active')")
        db.execute("INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
                   "VALUES ('s1','a1','S','prep','pending',?)", (YESTERDAY,))
        db.commit()
        result = sync_pipeline.check_overdue(db)
        db.commit()
        assert len(result["overdue"]) == 1
        assert db.execute("SELECT status FROM steps WHERE id='s1'").fetchone()["status"] == "due"

    def test_cascade_dates_returns_moves(self, db):
        seed_watching_calendar(db, trigger_date=(TODAY + timedelta(days=10)).isoformat())
        # condition-triggered activity with an estimated date that will move
        result = sync_pipeline.cascade_dates(db)
        assert "dates_cascaded" in result

    def test_pull_weather_without_key_reports_error(self, db, monkeypatch):
        monkeypatch.setattr(sync_pipeline, "OWM_KEY", "")
        result = sync_pipeline.pull_weather(db)
        assert result["errors"]
        assert result["pulled"] == []


class TestSummaryAggregation:
    def test_stage_results_match_summary(self, db):
        seed_watching_calendar(db)
        db.execute("INSERT INTO activities (id, domain_id, name, status) VALUES ('a2','d1','B','active')")
        db.execute("INSERT INTO steps (id, activity_id, name, step_type, status, due_date) "
                   "VALUES ('s1','a2','S','prep','pending',?)", (YESTERDAY,))
        db.commit()
        summary = sync_pipeline.SyncSummary()
        fired = sync_pipeline.evaluate_triggers(db, summary)
        db.commit()
        overdue = sync_pipeline.check_overdue(db, summary)
        db.commit()
        assert summary.triggers_fired == fired["fired"]
        assert summary.overdue == overdue["overdue"]

