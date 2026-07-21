#!/usr/bin/env python3
"""Step 31: export_dossier.py renders per-domain markdown state files."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    conn.execute("INSERT INTO domains (id,name,location,notes) VALUES ('d1','Test Yard','Murfreesboro,TN,US','Tall fescue, karst soil')")
    conn.execute("INSERT INTO domains (id,name,location) VALUES ('d2','Empty Domain','Nashville,TN,US')")

    # active (fired) activity with an open step
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,group_name,status,trigger_type,trigger_def,trigger_date,trigger_fired) "
        "VALUES ('a1','d1','Fungicide Watch','Disease','active','condition','{\"type\": \"condition\", \"all\": [{\"metric\": \"daily_low\", \"operator\": \">=\", \"value\": 68, \"sustained_days\": 3}]}','2026-07-05','2026-07-05T11:00:00')"
    )
    conn.execute(
        "INSERT INTO steps (id,activity_id,name,step_type,lead_days,status,due_date) "
        "VALUES ('s1','a1','Apply fungicide','follow_up',1,'due','2026-07-06')"
    )
    # watching activity with future date
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,group_name,status,trigger_type,trigger_def,trigger_date) "
        "VALUES ('a2','d1','Fall Overseed','Lawn','watching','compound','{\"type\": \"compound\", \"operator\": \"AND\", \"conditions\": [{\"type\": \"calendar\", \"after\": \"2026-09-05\"}, {\"type\": \"condition\", \"all\": [{\"metric\": \"daily_high\", \"operator\": \"<=\", \"value\": 85, \"sustained_days\": 3}]}]}','2026-09-05')"
    )
    # recently completed activity
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,status,trigger_type,trigger_def,completed_at) "
        "VALUES ('a3','d1','Spring Feed','completed','calendar','{\"type\": \"calendar\", \"date\": \"2026-04-01\"}',datetime('now','-3 days'))"
    )
    # old completed activity -- outside the 14-day window
    conn.execute(
        "INSERT INTO activities (id,domain_id,name,status,trigger_type,trigger_def,completed_at) "
        "VALUES ('a4','d1','Ancient Task','completed','calendar','{\"type\": \"calendar\", \"date\": \"2026-01-01\"}',datetime('now','-60 days'))"
    )
    # condition cache row
    conn.execute(
        "INSERT INTO conditions (id,activity_id,condition_type,definition,current_value,is_met,last_checked) "
        "VALUES ('c1','a2','temperature','{\"metric\": \"daily_high\", \"operator\": \"<=\", \"value\": 85, \"sustained_days\": 3}',94.9,0,'2026-07-21T11:00:00')"
    )
    # observation within window
    conn.execute(
        "INSERT INTO activity_log (item_type,item_id,action,new_value,source,timestamp) "
        "VALUES ('activity','obs1','observation',?, 'claude', datetime('now','-1 day'))",
        (json.dumps({"domain_id": "d1", "text": "Armyworms near the back fence", "affects": []}),),
    )
    # weather
    conn.execute(
        "INSERT INTO weather_log (location,weather_date,temp_high,temp_low,conditions,precipitation) "
        "VALUES ('Murfreesboro,TN,US',date('now'),94.9,75.7,'Clear',0.0)"
    )
    conn.commit()
    conn.close()
    return path


def run_export(db_path, out_dir):
    env = dict(os.environ)
    env["PLANSYNC_DB"] = db_path
    env["PLANSYNC_DOSSIER_DIR"] = out_dir
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "sync", "export_dossier.py")],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def exported(db_path, tmp_path):
    out = str(tmp_path / "dossiers")
    result = run_export(db_path, out)
    assert result.returncode == 0, result.stderr
    return out, result


class TestDossierExport:
    def test_one_file_per_domain(self, exported):
        out, _ = exported
        assert sorted(os.listdir(out)) == ["empty-domain.md", "test-yard.md"]

    def test_stdout_is_silent(self, exported):
        # runs inside the telegram-delivered cron wrapper; stdout must stay clean
        _, result = exported
        assert result.stdout == ""

    def test_header_and_hand_edit_warning(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "test-yard.md")).read()
        assert "# Test Yard" in text
        assert "Do not hand-edit" in text
        assert "Tall fescue, karst soil" in text

    def test_active_activity_with_steps(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "test-yard.md")).read()
        assert "Fungicide Watch" in text
        assert "Apply fungicide" in text
        assert "2026-07-06" in text

    def test_watching_activity_with_date(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "test-yard.md")).read()
        assert "Fall Overseed" in text
        assert "2026-09-05" in text

    def test_recent_completion_in_old_out(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "test-yard.md")).read()
        assert "Spring Feed" in text
        assert "Ancient Task" not in text

    def test_observation_present(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "test-yard.md")).read()
        assert "Armyworms near the back fence" in text

    def test_conditions_watch(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "test-yard.md")).read()
        assert "daily_high" in text
        assert "94.9" in text

    def test_weather_section(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "test-yard.md")).read()
        assert "Clear" in text

    def test_empty_domain_renders_without_error(self, exported):
        out, _ = exported
        text = open(os.path.join(out, "empty-domain.md")).read()
        assert "# Empty Domain" in text

    def test_rerun_overwrites_cleanly(self, db_path, exported):
        out, _ = exported
        result = run_export(db_path, out)
        assert result.returncode == 0, result.stderr
        assert sorted(os.listdir(out)) == ["empty-domain.md", "test-yard.md"]
