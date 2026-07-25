#!/usr/bin/env python3
"""
Domain JSON export: write a clean garden.json-format file from the live DB.

This is the DB-to-seed-file reverse path. The output is a valid load_domain
input: runtime fields (id, domain_id, status, trigger_date, trigger_fired,
completed_at, created_at, updated_at) are stripped, activity_id references in
trigger_def are resolved back to activity_ref name strings, and conditions
(derived from trigger_def) are omitted.

Run after export_dossier.py in the 6 AM cron chain:
    sync_pipeline.py  ->  export_dossier.py  ->  export_domain_json.py

Output layout:
    domains/{slug}/{slug}.json

The file is both a snapshot and a re-importable seed -- if the DB were lost,
load_domain(definition=<this JSON>) rebuilds it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plansync import engine  # noqa: E402

PLANSYNC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAINS_DIR = os.environ.get("PLANSYNC_DOMAINS_DIR", os.path.join(PLANSYNC_ROOT, "domains"))


def slugify(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-").replace("--", "-")


def export_domain(conn, domain):
    """Export a domain's activities+steps as a clean JSON definition."""
    did = domain["id"]

    # Build activity id->name lookup for dependency resolution
    acts = conn.execute(
        "SELECT * FROM activities WHERE domain_id=? ORDER BY sort_order, trigger_date",
        (did,),
    ).fetchall()
    id_to_name = {a["id"]: a["name"] for a in acts}

    # Load all steps grouped by activity
    steps_by_act = {}
    for s in conn.execute(
        "SELECT s.* FROM steps s JOIN activities a ON s.activity_id=a.id "
        "WHERE a.domain_id=? ORDER BY s.sort_order",
        (did,),
    ):
        steps_by_act.setdefault(s["activity_id"], []).append(dict(s))

    clean_activities = []
    for a in acts:
        act = {
            "name": a["name"],
            "description": a["description"],
        }
        if a["group_name"]:
            act["group_name"] = a["group_name"]

        act["trigger_type"] = a["trigger_type"]

        # Clean trigger_def: resolve activity_id -> activity_ref
        tdef_raw = a["trigger_def"]
        if isinstance(tdef_raw, str):
            tdef = json.loads(tdef_raw)
        else:
            tdef = dict(tdef_raw)
        tdef = _resolve_refs(tdef, id_to_name)
        act["trigger_def"] = tdef

        act["sort_order"] = a["sort_order"]

        # Steps
        clean_steps = []
        for s in steps_by_act.get(a["id"], []):
            step = {
                "name": s["name"],
                "step_type": s["step_type"],
                "lead_days": s["lead_days"],
            }
            if s.get("description"):
                step["description"] = s["description"]
            clean_steps.append(step)
        act["steps"] = clean_steps

        clean_activities.append(act)

    return {
        "name": domain["name"],
        "location": domain["location"],
        "notes": domain["notes"],
        "activities": clean_activities,
    }


def _resolve_refs(tdef, id_to_name):
    """Recursively resolve activity_id references to activity_ref names."""
    result = dict(tdef)
    if "activity_id" in result:
        ref_name = id_to_name.get(result["activity_id"], result["activity_id"])
        del result["activity_id"]
        result["activity_ref"] = ref_name

    # Compound triggers have nested conditions
    if "conditions" in result:
        result["conditions"] = [_resolve_refs(c, id_to_name) for c in result["conditions"]]

    return result


def main():
    if not os.path.exists(engine.db_path()):
        print(f"Database not found at {engine.db_path()}", file=sys.stderr)
        return 1

    conn = engine.get_db()
    try:
        domains = conn.execute("SELECT * FROM domains ORDER BY name").fetchall()
        for d in domains:
            slug = slugify(d["name"])
            domain_dir = os.path.join(DOMAINS_DIR, slug)
            os.makedirs(domain_dir, exist_ok=True)
            definition = export_domain(conn, d)
            path = os.path.join(domain_dir, f"{slug}.json")
            with open(path, "w") as f:
                json.dump(definition, f, indent=2)
                f.write("\n")
            print(f"  {d['name']}: {len(definition['activities'])} activities -> {path}",
                  file=sys.stderr)
        print(f"exported {len(domains)} domain definitions to {DOMAINS_DIR}/*/",
              file=sys.stderr)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
