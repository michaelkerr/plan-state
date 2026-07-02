#!/usr/bin/env python3
"""Test activity grouping (group_name) across schema, load_domain, MCP tools, and briefing context."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, os.path.join(ROOT, "sync"))

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
JSON_SCHEMA_PATH = os.path.join(ROOT, "domain_schema.json")


GARDEN = {
    "name": "Test Garden",
    "location": "Richmond,VA,US",
    "activities": [
        {
            "name": "Start Tomato Seeds",
            "group_name": "Tomatoes",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2026-02-15"},
            "steps": [{"name": "Buy tomato seed", "step_type": "prep", "lead_days": 7}],
        },
        {
            "name": "Transplant Tomatoes",
            "group_name": "Tomatoes",
            "trigger_type": "dependency",
            "trigger_def": {
                "type": "dependency",
                "activity_ref": "Start Tomato Seeds",
                "event": "completed",
                "offset_days": 42,
            },
        },
        {
            "name": "Plant Garlic",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2026-10-15"},
        },
    ],
}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
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
    return conn


@pytest.fixture(autouse=True)
def patch_db_path(db_path, monkeypatch):
    monkeypatch.setenv("PLANSYNC_DB", db_path)
    import server
    monkeypatch.setattr(server, "DB_PATH", db_path)


def call_tool(fn_name, args):
    import server
    conn = server.get_db()
    try:
        result = getattr(server, fn_name)(conn, args)
        return json.loads(result[0].text)
    finally:
        conn.close()


class TestJsonSchema:
    def test_group_name_validates(self):
        jsonschema = pytest.importorskip("jsonschema")
        with open(JSON_SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(instance=GARDEN, schema=schema)

    def test_non_string_group_name_rejected(self):
        jsonschema = pytest.importorskip("jsonschema")
        with open(JSON_SCHEMA_PATH) as f:
            schema = json.load(f)
        bad = json.loads(json.dumps(GARDEN))
        bad["activities"][0]["group_name"] = 42
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)


class TestLoadDomain:
    def test_group_name_persisted(self, db):
        result = call_tool("_load_domain", {"definition": GARDEN})
        assert "error" not in result

        rows = {
            r["name"]: r["group_name"]
            for r in db.execute("SELECT name, group_name FROM activities WHERE domain_id=?", (result["id"],)).fetchall()
        }
        assert rows["Start Tomato Seeds"] == "Tomatoes"
        assert rows["Transplant Tomatoes"] == "Tomatoes"
        assert rows["Plant Garlic"] is None

    def test_group_name_in_result(self, db):
        result = call_tool("_load_domain", {"definition": GARDEN})
        by_name = {a["name"]: a for a in result["activities"]}
        assert by_name["Start Tomato Seeds"]["group_name"] == "Tomatoes"
        assert by_name["Plant Garlic"]["group_name"] is None


class TestQueryTools:
    def test_get_domain_plan_returns_group_name(self, db):
        loaded = call_tool("_load_domain", {"definition": GARDEN})
        import server
        conn = server.get_db()
        try:
            plan = json.loads(server._get_domain_plan(conn, loaded["id"])[0].text)
        finally:
            conn.close()
        by_name = {a["name"]: a for a in plan["activities"]}
        assert by_name["Start Tomato Seeds"]["group_name"] == "Tomatoes"
        assert by_name["Plant Garlic"]["group_name"] is None

    def test_get_upcoming_returns_group_name(self, db):
        call_tool("_load_domain", {"definition": GARDEN})
        import server
        conn = server.get_db()
        try:
            result = json.loads(server._get_upcoming(conn, 14)[0].text)
        finally:
            conn.close()
        by_name = {a["name"]: a for a in result["items"]}
        # Feb calendar date is past, dependency has NULL trigger_date -- both in window
        assert by_name["Start Tomato Seeds"]["group_name"] == "Tomatoes"
        assert by_name["Transplant Tomatoes"]["group_name"] == "Tomatoes"


class TestCreateUpdateActivity:
    def test_create_activity_persists_group_name(self, db):
        domain = call_tool("_create_domain", {"name": "Garden"})
        created = call_tool("_create_activity", {
            "domain_id": domain["id"],
            "name": "Plant Onions",
            "group_name": "Onions",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2026-09-01"},
        })
        row = db.execute("SELECT group_name FROM activities WHERE id=?", (created["id"],)).fetchone()
        assert row["group_name"] == "Onions"

    def test_update_activity_sets_group_name(self, db):
        domain = call_tool("_create_domain", {"name": "Garden"})
        created = call_tool("_create_activity", {
            "domain_id": domain["id"],
            "name": "Plant Onions",
            "trigger_type": "calendar",
            "trigger_def": {"type": "calendar", "date": "2026-09-01"},
        })
        updated = call_tool("_update_activity", {"activity_id": created["id"], "group_name": "Onions"})
        assert updated["group_name"] == "Onions"
        row = db.execute("SELECT group_name FROM activities WHERE id=?", (created["id"],)).fetchone()
        assert row["group_name"] == "Onions"


class TestBriefingContext:
    def test_briefing_output_includes_group_name(self, db, db_path, tmp_path):
        call_tool("_load_domain", {"definition": GARDEN})
        env = dict(os.environ)
        env["PLANSYNC_DB"] = db_path
        env["PLANSYNC_OUTPUT_DIR"] = str(tmp_path / "sync-output")
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "briefing-context.py")],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stderr
        assert '"group_name": "Tomatoes"' in result.stdout


class TestTodoistNaming:
    def test_task_content_prefixes_group(self):
        import daily_sync
        assert daily_sync.task_content("Tomatoes", "Transplant Tomatoes") == "Tomatoes: Transplant Tomatoes"
        assert daily_sync.task_content(None, "Plant Garlic") == "Plant Garlic"
