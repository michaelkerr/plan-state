"""Tests for path instantiation."""

import os
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DISPATCH_DB", db_path)
    paths_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "paths")
    monkeypatch.setenv("DISPATCH_PATHS_DIR", paths_dir)
    from dispatch.store import init_db
    init_db(db_path)
    return db_path


class TestPathListing:
    def test_list_paths(self, db):
        from dispatch.instantiate import list_paths
        paths = list_paths()
        assert len(paths) >= 3
        ids = [p["id"] for p in paths]
        assert "garden-fall" in ids
        assert "lawn-cool-season" in ids
        assert "hunting-bow" in ids

    def test_load_path(self, db):
        from dispatch.instantiate import load_path
        path = load_path("garden-fall")
        assert path["name"] == "Fall Garden"
        assert len(path["items"]) >= 5


class TestInstantiate:
    def test_garden_fall(self, db):
        from dispatch.instantiate import instantiate
        from dispatch.store import connect, get_items

        params = {
            "zone": "7a",
            "frost_date_fall": "2026-10-20",
            "beds": [
                {"name": "Bed 1", "properties": {"sun": "full"}},
                {"name": "Bed 2", "properties": {"sun": "partial"}},
            ],
        }
        ids = instantiate("garden-fall", "garden", params)
        assert len(ids) > 0

        with connect() as conn:
            items = get_items(conn, domain="garden")

        # Should have items for both beds (per_entity) plus global items
        assert len(items) >= 5
        names = [i["name"] for i in items]
        assert any("Bed 1" in n for n in names)
        assert any("Bed 2" in n for n in names)
        for item in items:
            _assert_no_placeholders(item["trigger_def"])
            _assert_no_placeholders(item["checklist"])
        seed = next(i for i in items if i["name"] == "Start brassica seeds indoors")
        assert seed["trigger_def"]["date"] == "2026-10-20"

    def test_lawn(self, db):
        from dispatch.instantiate import instantiate
        from dispatch.store import connect, get_items

        params = {
            "zone": "7a",
            "lawn_sqft": 8000,
            "grass_type": "tall-fescue",
        }
        ids = instantiate("lawn-cool-season", "lawn", params)
        assert len(ids) >= 5

        with connect() as conn:
            items = get_items(conn, domain="lawn")
        names = [i["name"] for i in items]
        assert any("pre-emergent" in n.lower() for n in names)
        pre = next(i for i in items if "pre-emergent" in i["name"].lower())
        labels = [c["label"] for c in pre["checklist"]]
        assert any("8000" in label for label in labels)

    def test_hunting(self, db):
        from dispatch.instantiate import instantiate
        from dispatch.store import connect, get_items

        params = {
            "season_open": "2026-10-01",
            "season_close": "2026-01-15",
        }
        ids = instantiate("hunting-bow", "hunting", params)
        assert len(ids) >= 8

        with connect() as conn:
            items = get_items(conn, domain="hunting")
        names = [i["name"] for i in items]
        assert any("camera" in n.lower() for n in names)
        assert any("opening" in n.lower() for n in names)
        opening = next(i for i in items if i["name"] == "Opening day hunt")
        assert opening["trigger_def"]["date"] == "2026-10-01"
        late = next(i for i in items if i["name"] == "Late season strategy")
        assert late["trigger_def"]["date"] == "2026-01-15"

    def test_missing_required_param(self, db):
        from dispatch.instantiate import instantiate
        with pytest.raises(ValueError, match="Missing required"):
            instantiate("garden-fall", "garden", {"zone": "7a"})

    def test_dependency_chain(self, db):
        """After-triggers should reference real item IDs after instantiation."""
        from dispatch.instantiate import instantiate
        from dispatch.store import connect, get_items

        params = {
            "zone": "7a",
            "frost_date_fall": "2026-10-20",
            "beds": [{"name": "Bed 1"}],
        }
        ids = instantiate("garden-fall", "garden", params)

        with connect() as conn:
            items = get_items(conn, domain="garden")

        # Find items with after triggers and check they reference real IDs
        all_ids = {i["id"] for i in items}
        for item in items:
            tdef = item["trigger_def"]
            _check_refs(tdef, all_ids)


def _assert_no_placeholders(value):
    if isinstance(value, str):
        assert "{" not in value, value
    elif isinstance(value, list):
        for v in value:
            _assert_no_placeholders(v)
    elif isinstance(value, dict):
        for v in value.values():
            _assert_no_placeholders(v)


def _check_refs(tdef, valid_ids):
    if not isinstance(tdef, dict):
        return
    if tdef.get("type") == "after":
        ref = tdef.get("item_ref", "")
        # Either it's a real ID or an unresolvable ref name (for cross-entity)
        assert ref in valid_ids or not ref.startswith("0"), \
            f"Unresolved after ref: {ref}"
    if tdef.get("type") == "compound":
        for sub in tdef.get("triggers", []):
            _check_refs(sub, valid_ids)
