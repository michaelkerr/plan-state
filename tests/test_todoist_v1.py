#!/usr/bin/env python3
"""Test the Todoist unified v1 API integration: pagination, completion flag, weather upsert."""

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sync"))

import daily_sync

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    """Stub for the requests module: canned GET pages, records POSTs."""

    def __init__(self, get_pages):
        self.get_pages = list(get_pages)
        self.get_calls = []
        self.post_calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append({"url": url, "params": params or {}})
        return FakeResponse(self.get_pages.pop(0))

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": json})
        return FakeResponse({"id": "new-project-id"})


class TestGetOrCreateProject:
    def test_finds_project_on_first_page(self, monkeypatch):
        fake = FakeRequests([
            {"results": [{"id": "abc123", "name": "Yard"}], "next_cursor": None},
        ])
        monkeypatch.setattr(daily_sync, "requests", fake)
        assert daily_sync._get_or_create_project({}, "Yard") == "abc123"
        assert not fake.post_calls

    def test_follows_cursor_to_second_page(self, monkeypatch):
        fake = FakeRequests([
            {"results": [{"id": "p1", "name": "Other"}], "next_cursor": "CURSOR1"},
            {"results": [{"id": "p2", "name": "Yard"}], "next_cursor": None},
        ])
        monkeypatch.setattr(daily_sync, "requests", fake)
        assert daily_sync._get_or_create_project({}, "Yard") == "p2"
        assert fake.get_calls[1]["params"].get("cursor") == "CURSOR1"

    def test_creates_when_missing(self, monkeypatch):
        fake = FakeRequests([
            {"results": [{"id": "p1", "name": "Other"}], "next_cursor": None},
        ])
        monkeypatch.setattr(daily_sync, "requests", fake)
        assert daily_sync._get_or_create_project({}, "Yard") == "new-project-id"
        assert fake.post_calls[0]["json"] == {"name": "Yard"}

    def test_uses_v1_base_url(self, monkeypatch):
        fake = FakeRequests([{"results": [], "next_cursor": None}])
        monkeypatch.setattr(daily_sync, "requests", fake)
        daily_sync._get_or_create_project({}, "Yard")
        assert fake.get_calls[0]["url"].startswith("https://api.todoist.com/api/v1/")


class TestCompletionFlag:
    def test_checked_field(self):
        assert daily_sync.task_is_completed({"checked": True}) is True
        assert daily_sync.task_is_completed({"checked": False}) is False

    def test_legacy_is_completed_field(self):
        assert daily_sync.task_is_completed({"is_completed": True}) is True

    def test_missing_fields_default_false(self):
        assert daily_sync.task_is_completed({}) is False


class TestWeatherUpsert:
    @pytest.fixture
    def db(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        return conn

    def test_second_same_day_write_updates_not_inserts(self, db):
        daily_sync.upsert_weather_row(db, "Murfreesboro,TN,US", 88.0, 70.0, "Clear", 0.0, "{}")
        daily_sync.upsert_weather_row(db, "Murfreesboro,TN,US", 95.0, 69.0, "Clouds", 0.1, "{}")
        rows = db.execute("SELECT * FROM weather_log WHERE location=?", ("Murfreesboro,TN,US",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["temp_high"] == 95.0
        assert rows[0]["conditions"] == "Clouds"

    def test_different_locations_get_separate_rows(self, db):
        daily_sync.upsert_weather_row(db, "Murfreesboro,TN,US", 88.0, 70.0, "Clear", 0.0, "{}")
        daily_sync.upsert_weather_row(db, "Nashville,TN,US", 90.0, 72.0, "Clear", 0.0, "{}")
        count = db.execute("SELECT COUNT(*) as c FROM weather_log").fetchone()["c"]
        assert count == 2
