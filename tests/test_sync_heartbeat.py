#!/usr/bin/env python3
"""Test the sync heartbeat honesty (Step 20): a run with errors must never
report "ran clean" -- the daily Telegram message is the only dashboard."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))

import daily_sync


def test_clean_run_still_reports_clean():
    s = daily_sync.SyncSummary()
    out = s.to_stdout()
    assert "ran clean, no changes" in out


def test_errors_only_run_never_claims_clean():
    s = daily_sync.SyncSummary()
    s.errors.append("Weather pull failed for Murfreesboro: 401 Unauthorized")
    out = s.to_stdout()
    assert "ran clean" not in out
    assert "errors: 1" in out
    assert "Weather pull failed for Murfreesboro: 401 Unauthorized" in out


def test_multiple_errors_all_reported():
    s = daily_sync.SyncSummary()
    s.errors.append("Weather pull failed for Murfreesboro: timeout")
    s.errors.append("OPENWEATHERMAP_API_KEY not set, skipping weather pull")
    out = s.to_stdout()
    assert "errors: 2" in out
    assert "timeout" in out
    assert "OPENWEATHERMAP_API_KEY" in out


def test_multiline_error_reported_as_one_line():
    s = daily_sync.SyncSummary()
    s.errors.append("Fatal: something broke\nTraceback (most recent call last):\n  ...")
    out = s.to_stdout()
    assert "Fatal: something broke" in out
    assert "Traceback" not in out


def test_changes_and_errors_both_reported():
    s = daily_sync.SyncSummary()
    s.triggers_fired.append({"name": "Summer Fungicide Watch", "reason": "condition met"})
    s.errors.append("Todoist create failed for Water in application: 500")
    out = s.to_stdout()
    assert "Summer Fungicide Watch" in out
    assert "errors: 1" in out
    assert "Todoist create failed" in out


def test_changes_without_errors_has_no_error_section():
    s = daily_sync.SyncSummary()
    s.triggers_fired.append({"name": "Summer Fungicide Watch", "reason": "condition met"})
    out = s.to_stdout()
    assert "errors" not in out
