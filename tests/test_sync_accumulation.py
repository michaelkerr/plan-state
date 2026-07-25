#!/usr/bin/env python3
"""Step 38a: hourly runs accumulate into one daily JSON; the briefing reads
trigger fires from activity_log over the last 24h."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))
sys.path.insert(0, ROOT)

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
BRIEFING_SCRIPT = os.path.join(ROOT, "sync", "briefing_context.py")
TODAY = date.today()


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    import daily_sync
    d = str(tmp_path / "sync-output")
    monkeypatch.setattr(daily_sync, "OUTPUT_DIR", d)
    return d


def daily_file(out_dir):
    with open(os.path.join(out_dir, f"{TODAY.isoformat()}.json")) as f:
        return json.load(f)


class TestSaveOutputAccumulation:
    def test_two_runs_accumulate_events_and_replace_overdue(self, out_dir):
        import daily_sync
        s1 = daily_sync.SyncSummary()
        s1.triggers_fired.append({"name": "A", "reason": "calendar", "time": "T1"})
        s1.overdue.append({"name": "X: step", "due_date": "2026-07-20"})
        daily_sync.save_output(s1)

        s2 = daily_sync.SyncSummary()
        s2.triggers_fired.append({"name": "B", "reason": "condition", "time": "T2"})
        s2.dates_cascaded.append({"name": "S", "old_date": "a", "new_date": "b"})
        daily_sync.save_output(s2)

        out = daily_file(out_dir)
        assert [t["name"] for t in out["triggers_fired"]] == ["A", "B"]
        assert len(out["dates_cascaded"]) == 1
        assert out["overdue"] == []  # snapshot: latest run had none
        assert out["runs"] == 2
        assert out["last_run"]

    def test_first_run_counts_one(self, out_dir):
        import daily_sync
        daily_sync.save_output(daily_sync.SyncSummary())
        out = daily_file(out_dir)
        assert out["runs"] == 1

    def test_corrupt_prior_file_starts_fresh(self, out_dir):
        import daily_sync
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{TODAY.isoformat()}.json")
        with open(path, "w") as f:
            f.write("{not json")
        s = daily_sync.SyncSummary()
        s.triggers_fired.append({"name": "A", "reason": "r", "time": "T"})
        daily_sync.save_output(s)
        out = daily_file(out_dir)
        assert [t["name"] for t in out["triggers_fired"]] == ["A"]
        assert out["runs"] == 1

    def test_errors_accumulate(self, out_dir):
        import daily_sync
        s1 = daily_sync.SyncSummary()
        s1.errors.append("weather API timeout")
        daily_sync.save_output(s1)
        s2 = daily_sync.SyncSummary()
        s2.errors.append("weather API 500")
        daily_sync.save_output(s2)
        assert daily_file(out_dir)["errors"] == ["weather API timeout", "weather API 500"]


class TestEventTimestamps:
    def test_trigger_fire_entries_carry_time(self, tmp_path, monkeypatch):
        import daily_sync
        path = str(tmp_path / "test.db")
        monkeypatch.setenv("PLANSYNC_DB", path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','D','X')")
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO activities (id, domain_id, name, status, trigger_type, trigger_def, trigger_date) "
            "VALUES ('a1','d1','Act','watching','calendar',?,?)",
            (json.dumps({"type": "calendar", "date": yesterday}), yesterday),
        )
        conn.commit()
        summary = daily_sync.SyncSummary()
        daily_sync.evaluate_triggers(conn, summary)
        conn.commit()
        conn.close()
        assert summary.triggers_fired[0]["time"]


class TestBriefingLookback:
    def seed_db(self, path):
        conn = sqlite3.connect(path)
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','Garden','X')")
        for aid, name in (("a1", "RecentFire"), ("a2", "OldFire")):
            conn.execute(
                "INSERT INTO activities (id, domain_id, name, status) VALUES (?,?,?,'active')",
                (aid, "d1", name),
            )
        conn.execute(
            "INSERT INTO activity_log (timestamp, item_type, item_id, action, old_value, new_value, source) "
            "VALUES (datetime('now','-2 hours'),'activity','a1','trigger_fire','{\"status\": \"watching\"}',"
            "'{\"status\": \"active\", \"reason\": \"calendar: past\"}','cron')"
        )
        conn.execute(
            "INSERT INTO activity_log (timestamp, item_type, item_id, action, old_value, new_value, source) "
            "VALUES (datetime('now','-3 days'),'activity','a2','trigger_fire','{\"status\": \"watching\"}',"
            "'{\"status\": \"active\", \"reason\": \"calendar: old\"}','cron')"
        )
        conn.commit()
        conn.close()

    def run_briefing(self, db_path, out_dir):
        return subprocess.run(
            [sys.executable, BRIEFING_SCRIPT],
            env={**os.environ, "PLANSYNC_DB": db_path, "PLANSYNC_OUTPUT_DIR": out_dir},
            capture_output=True, text=True,
        )

    def test_last_24h_fires_included_older_excluded(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        self.seed_db(db_path)
        result = self.run_briefing(db_path, str(tmp_path / "out"))
        assert result.returncode == 0, result.stderr
        assert "Fired Since Yesterday" in result.stdout
        section = result.stdout.split("Fired Since Yesterday (last 24h) ===")[1].split("\n===")[0]
        assert "RecentFire" in section
        assert "OldFire" not in section
