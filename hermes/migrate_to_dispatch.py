"""migrate_to_dispatch — one-shot exporter from the current plansync DB.

Reads the existing plansync SQLite database and produces:
  1. Domain context YAML files (for plan-state)
  2. A summary of what would need to be instantiated in dispatch

This does NOT write to the dispatch DB — it exports data for review.
After review, use `dispatch instantiate` or direct import.

Usage:
    python -m scripts.migrate_to_dispatch [--db PATH] [--out DIR]
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

import yaml


def main():
    parser = argparse.ArgumentParser(description="Export plansync DB to dispatch format")
    parser.add_argument("--db", default=os.environ.get(
        "PLANSYNC_DB", "/opt/data/plansync/plansync.db"))
    parser.add_argument("--out", default="./migration-output")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Get domains
    domains = conn.execute("SELECT * FROM domains").fetchall()
    print(f"Found {len(domains)} domains")

    for domain_row in domains:
        domain = dict(domain_row)
        slug = domain["slug"] if "slug" in domain.keys() else domain.get("name", "unknown").lower().replace(" ", "-")
        print(f"\n--- Domain: {slug} ---")

        # Get activities
        activities = conn.execute(
            "SELECT * FROM activities WHERE domain_id=? ORDER BY sort_order, name",
            (domain["id"],)
        ).fetchall()

        # Get steps for each activity
        items_export = []
        entities = set()

        for act_row in activities:
            act = dict(act_row)
            # Parse trigger_def
            trigger_def = act.get("trigger_def", "{}")
            if isinstance(trigger_def, str):
                try:
                    trigger_def = json.loads(trigger_def)
                except json.JSONDecodeError:
                    trigger_def = {"type": "calendar", "date": "2026-01-01"}

            group = act.get("group_name", "")
            if group:
                entities.add(group)

            item = {
                "old_id": act["id"],
                "name": act["name"],
                "status": act.get("status", "watching"),
                "group": group,
                "trigger_def": trigger_def,
                "trigger_type": act.get("trigger_type", trigger_def.get("type", "?")),
                "trigger_date": act.get("trigger_date"),
                "due_date": act.get("trigger_date"),
                "notes": act.get("notes", ""),
            }
            items_export.append(item)

            # Steps become checklist items or separate items
            steps = conn.execute(
                "SELECT * FROM steps WHERE activity_id=? ORDER BY sort_order",
                (act["id"],)
            ).fetchall()

            step_items = []
            for step_row in steps:
                step = dict(step_row)
                step_items.append({
                    "label": step.get("name", ""),
                    "done": step.get("status") == "completed",
                    "old_step_id": step["id"],
                })

            if step_items:
                item["checklist"] = step_items

        # Build domain context
        context = {
            "domain": slug,
            "display_name": domain.get("name", slug),
            "location": {
                "name": domain.get("location", "Unknown"),
                "timezone": "America/Chicago",
            },
            "params": {},
            "entities": [
                {"type": "group", "name": g, "state": "active"}
                for g in sorted(entities)
            ],
            "season": {
                "name": f"Migrated {datetime.now().strftime('%Y-%m-%d')}",
            },
        }

        # Write context
        ctx_path = os.path.join(args.out, f"{slug}-context.yaml")
        with open(ctx_path, "w") as f:
            yaml.dump(context, f, default_flow_style=False, sort_keys=False)
        print(f"  Context: {ctx_path} ({len(context['entities'])} entities)")

        # Write items export
        items_path = os.path.join(args.out, f"{slug}-items.yaml")
        with open(items_path, "w") as f:
            yaml.dump(items_export, f, default_flow_style=False, sort_keys=False)
        print(f"  Items: {items_path} ({len(items_export)} items, "
              f"{sum(1 for i in items_export if i['status'] in ('watching','active'))} open)")

        # Summary
        statuses = {}
        for item in items_export:
            s = item["status"]
            statuses[s] = statuses.get(s, 0) + 1
        print(f"  Statuses: {statuses}")

    conn.close()
    print(f"\nExport complete → {args.out}/")
    print("Review the files, then use dispatch to import or re-instantiate.")


if __name__ == "__main__":
    main()
