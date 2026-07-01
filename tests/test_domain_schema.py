#!/usr/bin/env python3
"""Validate domain definitions against the JSON schema."""

import json
import os
import pytest

try:
    import jsonschema
    from jsonschema import validate, ValidationError
except ImportError:
    pytest.skip("jsonschema not installed", allow_module_level=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "domain_schema.json")
EXAMPLES_DIR = os.path.join(ROOT, "examples")


@pytest.fixture
def schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def load_example(name):
    with open(os.path.join(EXAMPLES_DIR, name)) as f:
        return json.load(f)


class TestValidExamples:
    def test_lawn_care_validates(self, schema):
        definition = load_example("lawn-care.json")
        validate(instance=definition, schema=schema)

    def test_fall_garden_validates(self, schema):
        definition = load_example("fall-garden.json")
        validate(instance=definition, schema=schema)

    def test_lawn_care_has_activities(self, schema):
        definition = load_example("lawn-care.json")
        assert len(definition["activities"]) == 4

    def test_fall_garden_has_activities(self, schema):
        definition = load_example("fall-garden.json")
        assert len(definition["activities"]) == 5

    def test_lawn_care_has_dependency_ref(self, schema):
        definition = load_example("lawn-care.json")
        spring_fert = definition["activities"][1]
        assert spring_fert["trigger_def"]["activity_ref"] == "Apply Pre-Emergent Herbicide"

    def test_all_trigger_types_covered(self, schema):
        lawn = load_example("lawn-care.json")
        garden = load_example("fall-garden.json")
        all_activities = lawn["activities"] + garden["activities"]
        trigger_types = {a["trigger_type"] for a in all_activities}
        assert "calendar" in trigger_types
        assert "compound" in trigger_types
        assert "dependency" in trigger_types


class TestInvalidDefinitions:
    def test_missing_name_rejected(self, schema):
        definition = {"activities": [{"name": "Test", "trigger_type": "calendar", "trigger_def": {"type": "calendar", "date": "2027-01-01"}}]}
        with pytest.raises(ValidationError, match="'name' is a required property"):
            validate(instance=definition, schema=schema)

    def test_missing_activities_rejected(self, schema):
        definition = {"name": "Test Domain"}
        with pytest.raises(ValidationError, match="'activities' is a required property"):
            validate(instance=definition, schema=schema)

    def test_empty_activities_rejected(self, schema):
        definition = {"name": "Test Domain", "activities": []}
        with pytest.raises(ValidationError):
            validate(instance=definition, schema=schema)

    def test_invalid_trigger_type_rejected(self, schema):
        definition = {
            "name": "Test",
            "activities": [{"name": "Act", "trigger_type": "magic", "trigger_def": {"type": "magic"}}],
        }
        with pytest.raises(ValidationError):
            validate(instance=definition, schema=schema)

    def test_missing_trigger_def_rejected(self, schema):
        definition = {
            "name": "Test",
            "activities": [{"name": "Act", "trigger_type": "calendar"}],
        }
        with pytest.raises(ValidationError, match="'trigger_def' is a required property"):
            validate(instance=definition, schema=schema)

    def test_invalid_step_type_rejected(self, schema):
        definition = {
            "name": "Test",
            "activities": [{
                "name": "Act",
                "trigger_type": "calendar",
                "trigger_def": {"type": "calendar", "date": "2027-01-01"},
                "steps": [{"name": "Bad Step", "step_type": "unknown", "lead_days": 1}],
            }],
        }
        with pytest.raises(ValidationError):
            validate(instance=definition, schema=schema)

    def test_negative_lead_days_rejected(self, schema):
        definition = {
            "name": "Test",
            "activities": [{
                "name": "Act",
                "trigger_type": "calendar",
                "trigger_def": {"type": "calendar", "date": "2027-01-01"},
                "steps": [{"name": "Bad Step", "step_type": "prep", "lead_days": -1}],
            }],
        }
        with pytest.raises(ValidationError):
            validate(instance=definition, schema=schema)

    def test_extra_properties_rejected(self, schema):
        definition = {
            "name": "Test",
            "activities": [{"name": "Act", "trigger_type": "calendar", "trigger_def": {"type": "calendar", "date": "2027-01-01"}}],
            "secret_field": "should fail",
        }
        with pytest.raises(ValidationError, match="Additional properties"):
            validate(instance=definition, schema=schema)

    def test_invalid_condition_metric_rejected(self, schema):
        definition = {
            "name": "Test",
            "activities": [{
                "name": "Act",
                "trigger_type": "condition",
                "trigger_def": {
                    "type": "condition",
                    "all": [{"metric": "moon_phase", "operator": ">=", "value": 0.5}],
                },
            }],
        }
        with pytest.raises(ValidationError):
            validate(instance=definition, schema=schema)
