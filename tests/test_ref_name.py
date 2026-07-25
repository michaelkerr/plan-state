#!/usr/bin/env python3
"""Step 46: ref_name -- stable identity for activities across renames."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))
sys.path.insert(0, ROOT)

from plansync.engine import slugify  # noqa: E402

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
MIGRATE_SCRIPT = os.path.join(ROOT, "scripts", "migrate-ref-name.py")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("PLANSYNC_DB", path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','Garden','X')")
    conn.commit()
    yield conn
    conn.close()


def call(fn, args):
    import server
    conn = server.get_db()
    try:
        return json.loads(getattr(server, fn)(conn, args)[0].text)
    finally:
        conn.close()


def add(activities):
    return call("_add_activities", {"domain_id": "d1", "activities": activities})


class TestSlugify:
    def test_basic(self):
        assert slugify("Sow Broccoli Indoors") == "sow-broccoli-indoors"

    def test_punctuation_and_case(self):
        assert slugify("Cut Potato Tops (S1 & N1)!") == "cut-potato-tops-s1-n1"

    def test_collapses_runs(self):
        assert slugify("A  --  B") == "a-b"


class TestRefNameCreate:
    def test_auto_generated(self, db):
        out = add([{"name": "Sow Broccoli Indoors"}])
        act = out["activities"][0]
        assert act["ref_name"] == "sow-broccoli-indoors"
        row = db.execute("SELECT ref_name FROM activities WHERE id=?", (act["id"],)).fetchone()
        assert row["ref_name"] == "sow-broccoli-indoors"

    def test_explicit_used_as_is(self, db):
        out = add([{"name": "Sow Broccoli Indoors", "ref_name": "broccoli-spring"}])
        assert out["activities"][0]["ref_name"] == "broccoli-spring"

    def test_slug_collision_uniquified(self, db):
        add([{"name": "Sow Peas"}])
        out = add([{"name": "Sow: Peas"}])  # slugs identically
        assert out["activities"][0]["ref_name"] == "sow-peas-2"

    def test_duplicate_explicit_ref_rejected(self, db):
        add([{"name": "A", "ref_name": "thing"}])
        out = add([{"name": "B", "ref_name": "thing"}])
        assert "error" in out

    def test_duplicate_in_same_batch_rejected(self, db):
        out = add([{"name": "A", "ref_name": "thing"}, {"name": "B", "ref_name": "thing"}])
        assert "error" in out


class TestRefNameImmutable:
    def test_rename_keeps_ref_name(self, db):
        act = add([{"name": "Sow Broccoli Indoors"}])["activities"][0]
        out = call("_update_activity", {"activity_id": act["id"], "name": "Sow Cabbage Indoors"})
        assert "error" not in out
        assert out["name"] == "Sow Cabbage Indoors"
        assert out["ref_name"] == "sow-broccoli-indoors"

    def test_update_ref_name_rejected(self, db):
        act = add([{"name": "Sow Broccoli Indoors"}])["activities"][0]
        out = call("_update_activity", {"activity_id": act["id"], "ref_name": "new-ref"})
        assert "error" in out
        assert "immutable" in out["error"]


class TestMigration:
    def test_backfills_unique_slugs(self, tmp_path):
        path = str(tmp_path / "live.db")
        conn = sqlite3.connect(path)
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        conn.executescript("""
            DROP INDEX IF EXISTS idx_activities_ref;
            ALTER TABLE activities DROP COLUMN ref_name;
        """)
        conn.execute("INSERT INTO domains (id, name, location) VALUES ('d1','G','X')")
        conn.execute("INSERT INTO domains (id, name, location) VALUES ('d2','Y','X')")
        conn.execute("INSERT INTO activities (id, domain_id, name, status) VALUES ('a1','d1','Sow Peas','active')")
        conn.execute("INSERT INTO activities (id, domain_id, name, status) VALUES ('a2','d1','Sow: Peas','active')")
        conn.execute("INSERT INTO activities (id, domain_id, name, status) VALUES ('a3','d2','Sow Peas','active')")
        conn.commit()
        conn.close()
        for _ in range(2):  # idempotent
            r = subprocess.run([sys.executable, MIGRATE_SCRIPT],
                               env={**os.environ, "PLANSYNC_DB": path},
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        refs = {r["id"]: r["ref_name"] for r in conn.execute("SELECT id, ref_name FROM activities")}
        assert refs["a1"] == "sow-peas"
        assert refs["a2"] == "sow-peas-2"
        assert refs["a3"] == "sow-peas"  # same slug fine in another domain
        conn.close()
