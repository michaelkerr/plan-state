"""Tests for path template validation, preview, and saving."""

import copy
import json
import os

import pytest
import yaml


REPO_PATHS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "paths")


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DISPATCH_DB", db_path)
    monkeypatch.setenv("DISPATCH_PATHS_DIR", REPO_PATHS)
    monkeypatch.setenv("DISPATCH_USER_PATHS_DIR", str(tmp_path / "custom"))
    from dispatch.store import init_db
    init_db(db_path)
    return db_path


BASE = {
    "id": "garlic",
    "version": "1.0.0",
    "name": "Garlic",
    "params": [
        {"name": "plant_date", "type": "date"},
        {"name": "beds", "type": "entity_ref"},
    ],
    "items": [
        {
            "ref": "plant",
            "name": "Plant garlic in {entity.name}",
            "per_entity": "beds",
            "trigger": {"type": "calendar", "date": "{plant_date}", "prep_days": 3},
            "checklist": [{"label": "Break bulbs into cloves"}],
        },
        {
            "ref": "mulch",
            "name": "Mulch garlic",
            "trigger": {
                "type": "compound",
                "op": "and",
                "triggers": [
                    {"type": "after", "item_ref": "plant", "offset_days": 7},
                    {"type": "condition",
                     "rules": [{"metric": "daily_low", "operator": "<=",
                                "value": 32, "sustained_days": 2}]},
                ],
            },
        },
    ],
}

PARAMS = {"plant_date": "2026-10-15", "beds": [{"name": "Bed 1"}, "Bed 2"]}


def _template(**changes):
    t = copy.deepcopy(BASE)
    t.update(changes)
    return t


def _with_item(index, **changes):
    t = copy.deepcopy(BASE)
    t["items"][index].update(changes)
    return t


def _errors(path_def):
    from dispatch.paths import validate_path
    return validate_path(path_def)[0]


def _warnings(path_def):
    from dispatch.paths import validate_path
    return validate_path(path_def)[1]


def _has(messages, text):
    return any(text in m for m in messages)


class TestBuiltinsValid:
    @pytest.mark.parametrize("path_id", ["garden-fall", "lawn-cool-season", "hunting-bow"])
    def test_builtin_has_no_errors(self, db, path_id):
        from dispatch.paths import load_path
        assert _errors(load_path(path_id)) == []

    def test_base_template_is_clean(self):
        assert _errors(BASE) == []
        assert _warnings(BASE) == [
            "items[1] (mulch).trigger.triggers[0]: 'plant' is created once per beds; "
            "this item waits only on the last copy"
        ]


class TestStructuralErrors:
    def test_missing_top_level(self):
        assert _has(_errors({"id": "x"}), "Missing top-level field 'items'")

    def test_unquoted_version(self):
        assert _has(_errors(_template(version=1.0)), "quote it")

    def test_bad_id(self):
        assert _has(_errors(_template(id="My Garden")), "lowercase")

    def test_unknown_param_type(self):
        t = _template(params=[{"name": "plant_date", "type": "datetime"},
                              {"name": "beds", "type": "entity_ref"}])
        assert _has(_errors(t), "type must be one of")

    def test_unknown_trigger_type(self):
        t = _with_item(0, trigger={"type": "weather"})
        assert _has(_errors(t), "type 'weather' is not one of")

    def test_trigger_field_typo(self):
        t = _with_item(0, trigger={"type": "calendar", "date": "{plant_date}", "prep_day": 3})
        assert _has(_errors(t), "unknown field 'prep_day'")

    def test_unsupported_metric(self):
        t = _with_item(1, trigger={"type": "condition", "rules": [
            {"metric": "soil_temp", "operator": ">=", "value": 50}]})
        assert _has(_errors(t), "soil temperature")

    def test_after_forward_reference(self):
        t = copy.deepcopy(BASE)
        t["items"].reverse()
        assert _has(_errors(t), "must be the ref of an item defined above")

    def test_after_fired_event_rejected(self):
        t = _with_item(1, trigger={"type": "after", "item_ref": "plant", "event": "fired"})
        assert _has(_errors(t), "event 'fired' is not supported")

    def test_negative_offset_rejected(self):
        t = _with_item(1, trigger={"type": "after", "item_ref": "plant", "offset_days": -3})
        assert _has(_errors(t), "0 or more")

    def test_compound_needs_two(self):
        t = _with_item(1, trigger={"type": "compound", "op": "and", "triggers": [
            {"type": "calendar", "date": "{plant_date}"}]})
        assert _has(_errors(t), "at least 2")

    def test_recurrence_rejected(self):
        t = _with_item(1, recurrence="yearly")
        assert _has(_errors(t), "Recurrence is not supported")

    def test_duplicate_ref(self):
        t = _with_item(1, ref="plant")
        assert _has(_errors(t), "duplicate ref 'plant'")

    def test_unknown_placeholder(self):
        t = _with_item(1, name="Mulch {crop}")
        assert _has(_errors(t), "unknown placeholder {crop}")

    def test_entity_placeholder_needs_per_entity(self):
        t = _with_item(1, name="Mulch {entity.name}")
        assert _has(_errors(t), "only works on items with per_entity")

    def test_per_entity_must_be_entity_param(self):
        t = _with_item(0, per_entity="plant_date")
        assert _has(_errors(t), "must be an entity_ref or list param")

    def test_date_placeholder_needs_date_param(self):
        t = _template(params=[{"name": "plant_date", "type": "string"},
                              {"name": "beds", "type": "entity_ref"}])
        assert _has(_errors(t), "must have type 'date'")

    def test_bad_date_literal(self):
        t = _with_item(0, trigger={"type": "calendar", "date": "Oct 15"})
        assert _has(_errors(t), "is not a YYYY-MM-DD date")


class TestWarnings:
    def test_hardcoded_date(self):
        t = _with_item(0, trigger={"type": "calendar", "date": "2026-10-15"})
        assert _has(_warnings(t), "hardcoded date 2026-10-15")

    def test_unused_param(self):
        t = copy.deepcopy(BASE)
        t["params"].append({"name": "zone", "type": "string"})
        assert _has(_warnings(t), "Param 'zone' is declared but never used")


class TestPreview:
    def test_preview_expands_entities_and_dates(self):
        from dispatch.paths import check_path
        result = check_path(BASE, PARAMS)
        assert result["valid"], result["errors"]
        names = [p["name"] for p in result["preview"]]
        assert names == ["Plant garlic in Bed 1", "Plant garlic in Bed 2", "Mulch garlic"]
        assert result["preview"][0]["when"] == "on 2026-10-12 (3 days before 2026-10-15)"
        assert result["preview"][2]["when"] == (
            "7 days after 'Plant garlic in Bed 2' is done AND "
            "when daily low <= 32°F for 2 days in a row"
        )

    def test_negative_prep_reads_as_after(self):
        from dispatch.paths import describe_trigger
        assert describe_trigger({"type": "calendar", "date": "2026-10-20", "prep_days": -30}) == \
            "on 2026-11-19 (30 days after 2026-10-20)"

    def test_no_params_means_no_preview(self):
        from dispatch.paths import check_path
        result = check_path(BASE)
        assert result["valid"] and result["preview"] is None

    def test_missing_param_blocks_preview(self):
        from dispatch.paths import check_path
        result = check_path(BASE, {"beds": ["Bed 1"]})
        assert not result["valid"]
        assert _has(result["errors"], "Missing required parameter: plant_date")

    def test_bad_param_value(self):
        from dispatch.paths import check_path
        result = check_path(BASE, {**PARAMS, "plant_date": "next week"})
        assert _has(result["errors"], "is not a YYYY-MM-DD date")

    def test_optional_param_without_value_is_caught(self):
        from dispatch.paths import check_path
        t = copy.deepcopy(BASE)
        t["params"].append({"name": "variety", "type": "string", "required": False})
        t["items"][1]["name"] = "Mulch {variety} garlic"
        result = check_path(t, PARAMS)
        assert not result["valid"]
        assert _has(result["errors"], "{variety} has no value")

    def test_defaults_fill_preview(self, db):
        from dispatch.paths import check_path, load_path
        result = check_path(load_path("lawn-cool-season"), {"zone": "7a"})
        assert result["valid"], result["errors"]
        pre = result["preview"][0]
        assert any("5000" in label for label in pre["checklist"])

    def test_builtin_previews_cleanly(self, db):
        from dispatch.paths import check_path, load_path
        result = check_path(load_path("hunting-bow"),
                            {"season_open": "2026-10-01", "season_close": "2027-01-15"})
        assert result["valid"], result["errors"]
        rut = next(p for p in result["preview"] if p["ref"] == "rut-hunt")
        assert rut["when"] == "on 2026-10-31 (30 days after 2026-10-01)"


class TestSaveAndUse:
    def test_save_lists_loads_and_instantiates(self, db, tmp_path):
        from dispatch.paths import save_path, list_paths, load_path
        from dispatch.instantiate import instantiate
        from dispatch.store import connect, get_items

        target = save_path(yaml.safe_dump(BASE, sort_keys=False))
        assert target == str(tmp_path / "custom" / "garlic" / "path.yaml")

        listed = {p["id"]: p for p in list_paths()}
        assert listed["garlic"]["source"] == "custom"
        assert listed["garden-fall"]["source"] == "built-in"
        assert load_path("garlic")["name"] == "Garlic"

        ids = instantiate("garlic", "garden", PARAMS)
        assert len(ids) == 3
        with connect() as conn:
            items = {i["name"]: i for i in get_items(conn, domain="garden")}
        mulch = items["Mulch garlic"]["trigger_def"]
        assert mulch["triggers"][0]["item_ref"] == items["Plant garlic in Bed 2"]["id"]

    def test_save_keeps_comments(self, db):
        from dispatch.paths import save_path
        text = "# my notes\n" + yaml.safe_dump(BASE, sort_keys=False)
        with open(save_path(text)) as f:
            assert f.read().startswith("# my notes")

    def test_save_refuses_builtin_id(self, db):
        from dispatch.paths import save_path
        with pytest.raises(ValueError, match="built-in"):
            save_path(yaml.safe_dump(_template(id="garden-fall")))

    def test_save_refuses_invalid(self, db):
        from dispatch.paths import save_path
        with pytest.raises(ValueError, match="Template has errors"):
            save_path(yaml.safe_dump(_with_item(0, trigger={"type": "weather"})))

    def test_save_rejects_non_mapping(self, db):
        from dispatch.paths import save_path
        with pytest.raises(ValueError, match="YAML mapping"):
            save_path("- just\n- a list\n")

    def test_instantiate_refuses_invalid_template(self, db, tmp_path):
        from dispatch.instantiate import instantiate
        bad_dir = tmp_path / "custom" / "garlic"
        bad_dir.mkdir(parents=True)
        (bad_dir / "path.yaml").write_text(
            yaml.safe_dump(_with_item(0, trigger={"type": "weather"})))
        with pytest.raises(ValueError, match="is invalid"):
            instantiate("garlic", "garden", PARAMS)

    def test_instantiate_applies_defaults(self, db):
        from dispatch.instantiate import instantiate
        from dispatch.store import connect, get_items
        instantiate("lawn-cool-season", "lawn", {"zone": "7a"})
        with connect() as conn:
            items = get_items(conn, domain="lawn")
        pre = next(i for i in items if "pre-emergent" in i["name"].lower())
        assert any("5000" in c["label"] for c in pre["checklist"])


class TestSkillExample:
    def test_path_authoring_skill_example_is_valid(self):
        import re
        from dispatch.paths import check_path
        skill = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "skills", "path-authoring", "SKILL.md")
        with open(skill) as f:
            block = re.search(r"```yaml\n(.*?)```", f.read(), re.S).group(1)
        result = check_path(yaml.safe_load(block),
                            {"plant_date": "2026-10-15", "beds": [{"name": "Bed 1"}]})
        assert result["valid"], result["errors"]


class TestNegativePrepFires:
    def test_negative_prep_fires_after_target(self, db):
        from dispatch.eval import _check_trigger
        from dispatch.store import connect
        tdef = {"type": "calendar", "date": "2026-10-20", "prep_days": -30}
        with connect() as conn:
            assert _check_trigger(conn, tdef, "2026-10-20", "x") == (False, None)
            assert _check_trigger(conn, tdef, "2026-11-19", "x") == (True, "2026-11-19")


class TestDraftPathTool:
    def _call(self, args):
        from dispatch.server import _draft_path
        return _draft_path(args)

    def _body(self, result):
        return json.loads(result.content[0].text)

    def test_preview_from_yaml(self, db):
        result = self._call({"yaml": yaml.safe_dump(BASE), "params": PARAMS})
        assert result.isError is not True
        body = self._body(result)
        assert body["valid"] and len(body["preview"]) == 3
        assert "saved_to" not in body

    def test_check_existing(self, db):
        body = self._body(self._call({"path_id": "garden-fall"}))
        assert body["valid"] and body["preview"] is None

    def test_save(self, db, tmp_path):
        body = self._body(self._call({"yaml": yaml.safe_dump(BASE), "save": True}))
        assert body["saved_to"] == str(tmp_path / "custom" / "garlic" / "path.yaml")

    def test_needs_yaml_or_path_id(self, db):
        assert self._call({}).isError is True

    def test_save_existing_refused(self, db):
        assert self._call({"path_id": "garden-fall", "save": True}).isError is True

    def test_invalid_returns_errors_as_data(self, db):
        result = self._call({"yaml": yaml.safe_dump(_with_item(0, trigger={"type": "weather"}))})
        assert result.isError is not True
        assert not self._body(result)["valid"]
