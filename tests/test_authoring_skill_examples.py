"""Regression: the JSON examples in skills/domain-authoring.md must validate
against the server's actual validators (Step 14). If validation rules change
(e.g. Step 22 rejecting conditions arrays), this fails until the skill's
examples are updated to match -- the skill must never teach a format the
tools reject."""

import importlib.util
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_PATH = os.path.join(ROOT, "skills", "domain-authoring.md")

spec = importlib.util.spec_from_file_location(
    "server", os.path.join(ROOT, "mcp-server", "server.py")
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def read_skill():
    with open(SKILL_PATH) as f:
        return f.read()


def fenced_json_blocks(text):
    blocks = []
    for m in re.finditer(r"```json\n(.*?)```", text, re.DOTALL):
        try:
            blocks.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass  # fragments (bare trigger_defs etc.) are validated via the full examples
    return blocks


class TestSkillExamples(unittest.TestCase):
    def setUp(self):
        self.text = read_skill()

    def test_create_mode_example_validates(self):
        domains = [
            b for b in fenced_json_blocks(self.text)
            if isinstance(b, dict) and "name" in b and "activities" in b
        ]
        self.assertGreaterEqual(len(domains), 1, "skill must contain a complete domain example")
        for defn in domains:
            errors = server._validate_domain_definition(defn)
            self.assertEqual(errors, [], f"create example '{defn['name']}' fails validation: {errors}")

    def test_amend_mode_example_validates(self):
        # The amend example is shown as an add_activities(...) call; extract the
        # activities=[...] array from that fence.
        m = re.search(r"```\n" r"add_activities\(.*?activities=(\[.*?\])\s*\)\s*\n```", self.text, re.DOTALL)
        self.assertIsNotNone(m, "skill must contain an add_activities amend example")
        activities = json.loads(m.group(1))
        self.assertGreaterEqual(len(activities), 3, "amend example should show a multi-activity chain")

        errors = server._validate_activities(activities, [], existing_names={"Bed Prep S1"})
        self.assertEqual(errors, [], f"amend example fails validation: {errors}")

    def test_amend_example_is_grouped_dependency_chain(self):
        # Step 14 acceptance: multi-phase crop under one group, linked by dependency refs.
        m = re.search(r"```\n" r"add_activities\(.*?activities=(\[.*?\])\s*\)\s*\n```", self.text, re.DOTALL)
        activities = json.loads(m.group(1))
        groups = {a.get("group_name") for a in activities}
        self.assertEqual(len(groups), 1, "amend example activities should share one group")
        names = {a["name"] for a in activities}
        dep_refs = {
            a["trigger_def"]["activity_ref"]
            for a in activities
            if a["trigger_def"].get("type") == "dependency"
        }
        self.assertTrue(dep_refs, "amend example should contain dependency triggers")
        self.assertTrue(
            dep_refs <= names,
            f"dependency refs {dep_refs} must resolve within the example batch",
        )

    def test_dependency_ref_against_existing_activity_validates(self):
        # The skill claims amend-mode refs may name activities already in the domain.
        batch = [{
            "name": "Mulch Tomatoes",
            "group_name": "Tomatoes",
            "trigger_type": "dependency",
            "trigger_def": {"type": "dependency", "activity_ref": "Bed Prep S1", "event": "completed"},
        }]
        errors = server._validate_activities(batch, [], existing_names={"Bed Prep S1"})
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
