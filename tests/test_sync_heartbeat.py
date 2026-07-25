#!/usr/bin/env python3
"""Sync heartbeat contract.

Step 20 (honesty): a run with errors must never report "ran clean".
Step 32 (quiet): the heartbeat carries counts only -- item names belong to
the 6:15 briefing, which reads the full JSON summary. Errors stay itemized.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))

import sync_pipeline


def test_clean_run_still_reports_clean():
    s = sync_pipeline.SyncSummary()
    out = s.to_stdout()
    assert "ran clean, no changes" in out


def test_errors_only_run_never_claims_clean():
    s = sync_pipeline.SyncSummary()
    s.errors.append("Weather pull failed for Murfreesboro: 401 Unauthorized")
    out = s.to_stdout()
    assert "ran clean" not in out
    assert "errors: 1" in out
    assert "Weather pull failed for Murfreesboro: 401 Unauthorized" in out


def test_multiple_errors_all_reported():
    s = sync_pipeline.SyncSummary()
    s.errors.append("Weather pull failed for Murfreesboro: timeout")
    s.errors.append("OPENWEATHERMAP_API_KEY not set, skipping weather pull")
    out = s.to_stdout()
    assert "errors: 2" in out
    assert "timeout" in out
    assert "OPENWEATHERMAP_API_KEY" in out


def test_multiline_error_reported_as_one_line():
    s = sync_pipeline.SyncSummary()
    s.errors.append("Fatal: something broke\nTraceback (most recent call last):\n  ...")
    out = s.to_stdout()
    assert "Fatal: something broke" in out
    assert "Traceback" not in out


def test_changes_and_errors_both_reported():
    s = sync_pipeline.SyncSummary()
    s.triggers_fired.append({"name": "Summer Fungicide Watch", "reason": "condition met"})
    s.errors.append("Weather pull failed for Murfreesboro: 500")
    out = s.to_stdout()
    assert "triggers fired 1" in out
    assert "errors: 1" in out
    assert "Weather pull failed" in out


def test_changes_without_errors_has_no_error_section():
    s = sync_pipeline.SyncSummary()
    s.triggers_fired.append({"name": "Summer Fungicide Watch", "reason": "condition met"})
    out = s.to_stdout()
    assert "errors" not in out


# ── Step 32: counts only, no item detail ─────────────────────

def _busy_summary():
    s = sync_pipeline.SyncSummary()
    s.triggers_fired.append({"name": "Summer Fungicide Watch", "reason": "condition met"})
    s.dates_cascaded.append({"name": "Apply fungicide", "old_date": "2026-07-05", "new_date": "2026-07-08"})
    s.overdue.append({"name": "Yard: Water in application", "due_date": "2026-07-15"})
    s.overdue.append({"name": "Garden: Dig potatoes", "due_date": "2026-07-17"})
    return s


def test_heartbeat_reports_counts():
    out = _busy_summary().to_stdout()
    assert "triggers fired 1" in out
    assert "dates cascaded 1" in out
    assert "overdue 2" in out


def test_heartbeat_contains_no_item_names():
    out = _busy_summary().to_stdout()
    for detail in ("Summer Fungicide Watch", "Apply fungicide", "Water in application",
                   "Dig potatoes", "2026-07-15", "2026-07-17"):
        assert detail not in out


def test_heartbeat_is_short():
    s = _busy_summary()
    for i in range(30):
        s.overdue.append({"name": f"Item {i}", "due_date": "2026-07-01"})
    assert len(s.to_stdout().splitlines()) == 1


def test_json_summary_keeps_full_detail():
    # the briefing reads this file; item detail must survive there
    d = _busy_summary().to_dict()
    assert d["triggers_fired"][0]["name"] == "Summer Fungicide Watch"
    assert d["dates_cascaded"][0]["new_date"] == "2026-07-08"
    assert d["overdue"][0]["due_date"] == "2026-07-15"


def test_errors_itemized_alongside_counts():
    s = _busy_summary()
    s.errors.append("Weather pull failed: timeout")
    out = s.to_stdout()
    assert "overdue 2" in out
    assert "Weather pull failed: timeout" in out
