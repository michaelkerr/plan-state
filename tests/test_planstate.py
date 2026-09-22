"""Tests for planstate context, reconcile, and adapters."""

import os
import pytest
import yaml


@pytest.fixture
def ctx_dir(tmp_path, monkeypatch):
    d = tmp_path / "domains"
    d.mkdir()
    monkeypatch.setenv("PLANSTATE_CONTEXT_DIR", str(d))
    monkeypatch.setenv("DISPATCH_DB", str(tmp_path / "dispatch.db"))
    from dispatch.store import init_db
    init_db(str(tmp_path / "dispatch.db"))
    return d


@pytest.fixture
def sample_context():
    return {
        "domain": "garden",
        "display_name": "Fall Garden 2026",
        "location": {"name": "Nashville,TN,US", "timezone": "America/Chicago"},
        "params": {"zone": "7a", "frost_date_fall": "2026-10-20"},
        "entities": [
            {"type": "bed", "name": "Bed 1",
             "properties": {"soil_type": "clay-loam", "sun": "full"},
             "state": "planted"},
            {"type": "bed", "name": "Bed 2",
             "properties": {"soil_type": "sandy-loam", "sun": "partial"},
             "state": "fallow"},
        ],
        "season": {"name": "Fall 2026", "start_date": "2026-08-15",
                    "end_date": "2026-11-30"},
    }


class TestContext:
    def test_save_and_load(self, ctx_dir, sample_context):
        from planstate.context import save_context, load_context
        save_context(sample_context)
        loaded = load_context("garden")
        assert loaded["domain"] == "garden"
        assert loaded["display_name"] == "Fall Garden 2026"
        assert len(loaded["entities"]) == 2

    def test_validation_missing_domain(self, ctx_dir):
        from planstate.context import validate_context
        errors = validate_context({"location": {"name": "X"}})
        assert any("domain" in e for e in errors)

    def test_validation_missing_location(self, ctx_dir):
        from planstate.context import validate_context
        errors = validate_context({"domain": "test"})
        assert any("location" in e for e in errors)

    def test_validation_valid(self, sample_context):
        from planstate.context import validate_context
        errors = validate_context(sample_context)
        assert errors == []

    def test_get_entities_by_type(self, ctx_dir, sample_context):
        from planstate.context import save_context, load_context, get_entities
        save_context(sample_context)
        ctx = load_context("garden")
        beds = get_entities(ctx, entity_type="bed")
        assert len(beds) == 2
        assert beds[0]["name"] == "Bed 1"

    def test_update_entity_state(self, sample_context):
        from planstate.context import update_entity_state
        updated = update_entity_state(sample_context, "Bed 1", "harvesting")
        assert updated
        assert sample_context["entities"][0]["state"] == "harvesting"

    def test_list_contexts(self, ctx_dir, sample_context):
        from planstate.context import save_context, list_contexts
        save_context(sample_context)
        contexts = list_contexts()
        assert len(contexts) == 1
        assert contexts[0]["domain"] == "garden"

    def test_record_path_activation(self, sample_context):
        from planstate.context import record_path_activation
        record_path_activation(sample_context, "garden-fall@1.0",
                               {"zone": "7a"})
        assert len(sample_context["active_paths"]) == 1
        assert sample_context["active_paths"][0]["path_id"] == "garden-fall@1.0"


class TestReconcile:
    def test_empty_reconcile(self, ctx_dir, sample_context):
        from planstate.context import save_context
        from planstate.reconcile import reconcile
        save_context(sample_context)
        result = reconcile("garden")
        assert result["domain"] == "garden"
        assert result["dispatch_items"] == 0

    def test_stale_items_detected(self, ctx_dir, sample_context):
        from planstate.context import save_context
        from planstate.reconcile import reconcile
        from dispatch.store import connect, insert_item
        save_context(sample_context)

        with connect() as conn:
            insert_item(conn, "garden", "Old task",
                        {"type": "calendar", "date": "2025-01-01"},
                        source_ref="transplant:Bed 1")
            # Backdate created_at to make it stale
            conn.execute(
                "UPDATE items SET created_at='2025-01-01T00:00:00'"
            )
            conn.commit()

        result = reconcile("garden")
        stale = [i for i in result["issues"] if i["type"] == "stale_item"]
        assert len(stale) >= 1


class TestObsidianAdapter:
    def test_save_and_load(self, tmp_path, sample_context):
        vault = tmp_path / "vault"
        (vault / "domains").mkdir(parents=True)

        from planstate.adapters.obsidian import ObsidianAdapter
        adapter = ObsidianAdapter(vault_path=str(vault))
        adapter.save(sample_context)

        loaded = adapter.load("garden")
        assert loaded["domain"] == "garden"
        assert len(loaded["entities"]) == 2

    def test_preserves_body(self, tmp_path, sample_context):
        vault = tmp_path / "vault"
        (vault / "domains").mkdir(parents=True)

        note_path = vault / "domains" / "garden.md"
        note_path.write_text(
            "---\n"
            + yaml.dump(sample_context, default_flow_style=False)
            + "---\n"
            + "# Garden Notes\n\nSome important notes.\n"
        )

        from planstate.adapters.obsidian import ObsidianAdapter
        adapter = ObsidianAdapter(vault_path=str(vault))

        ctx = adapter.load("garden")
        ctx["params"]["zone"] = "7b"
        adapter.save(ctx)

        content = note_path.read_text()
        assert "# Garden Notes" in content
        assert "7b" in content

    def test_list_domains(self, tmp_path, sample_context):
        vault = tmp_path / "vault"
        (vault / "domains").mkdir(parents=True)

        from planstate.adapters.obsidian import ObsidianAdapter
        adapter = ObsidianAdapter(vault_path=str(vault))
        adapter.save(sample_context)

        domains = adapter.list_domains()
        assert len(domains) == 1
        assert domains[0]["domain"] == "garden"
