#!/usr/bin/env python3
"""
Dossier export: one markdown state file per domain, so a Claude session
WITHOUT MCP access (mobile, web chat) can read current plan state instantly.
Deterministic, zero LLM tokens. Runs after daily_sync in the 6 AM cron; all
human-facing output goes to files, never stdout (the cron wrapper's stdout is
delivered to Telegram).

Dossier files are generated artifacts -- never hand-edit them.

Output layout: each domain's dossier is written to
  domains/{slug}/dossier.md
alongside any rotation config and reference doc that domain owns.
"""

import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plansync import engine  # noqa: E402

PLANSYNC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAINS_DIR = os.environ.get("PLANSYNC_DOMAINS_DIR", os.path.join(PLANSYNC_ROOT, "domains"))
RECENT_DAYS = 14


def slugify(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-").replace("--", "-")


def load_rotation(slug):
    """Load rotation config if one exists for this domain."""
    path = os.path.join(DOMAINS_DIR, slug, "rotation.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"warning: could not load rotation config {path}: {e}", file=sys.stderr)
        return None


def garden_year(today, start_month=9):
    """Garden year = calendar year + 1 if we're past start_month (Sep by default)."""
    if today.month >= start_month:
        return today.year + 1
    return today.year


def render_rotation(rotation, today):
    """Render current rotation position as markdown lines."""
    lines = []
    gy = garden_year(today, rotation.get("garden_year_start_month", 9))
    start = rotation["start_year"]
    cycle = rotation["cycle_length"]
    march = rotation["march"]
    sections = rotation.get("sections", sorted(march[0].keys()))

    # Before the rotation formally starts, show the first year's assignments
    # (prep activities for Year 1 run months before the garden year opens).
    gy = max(gy, start)

    idx = (gy - start) % cycle
    assignments = march[idx]

    lines.append(f"## Rotation position (garden year {gy})")
    lines.append("")
    lines.append("| Section | Group |")
    lines.append("|---|---|")
    for sec in sections:
        lines.append(f"| {sec} | {assignments.get(sec, '?')} |")
    lines.append("")
    return lines


def fmt_trigger(activity, names=None):
    tdef = activity.get("trigger_def") or {}
    t = tdef.get("type", activity.get("trigger_type", "?"))
    if t == "calendar":
        return f"calendar {tdef.get('date') or tdef.get('after', '?')}"
    if t == "condition":
        clauses = [f"{c.get('metric')} {c.get('operator')} {c.get('value')}"
                   + (f" x{c.get('sustained_days')}d" if c.get("sustained_days", 1) > 1 else "")
                   for c in tdef.get("all", [])]
        return "condition: " + ", ".join(clauses)
    if t == "dependency":
        dep_id = tdef.get("activity_id", "?")
        dep = (names or {}).get(dep_id, dep_id)
        return f"after \"{dep}\" completes" + (
            f" +{tdef['offset_days']}d" if tdef.get("offset_days") else "")
    if t == "compound":
        legs = []
        for sub in tdef.get("conditions", []):
            legs.append(fmt_trigger({"trigger_def": sub, "trigger_type": sub.get("type")}, names))
        return f" {tdef.get('operator', 'AND')} ".join(legs)
    return t


def render_domain(conn, domain):
    lines = []
    add = lines.append
    did = domain["id"]
    slug = slugify(domain["name"])

    add(f"# {domain['name']} -- plan state")
    add("")
    add(f"Generated {datetime.now().isoformat(timespec='seconds')} by export_dossier.py from the live plansync DB.")
    add("Do not hand-edit: this file is regenerated daily by the 6 AM sync. For live")
    add("queries or changes, use the plansync MCP tools.")
    add("")
    if domain["location"]:
        add(f"**Location:** {domain['location']}")
    if domain["notes"]:
        add(f"**Notes:** {domain['notes']}")
    add("")

    # Reference doc pointer (if a rotation config names one)
    rotation = load_rotation(slug)
    if rotation:
        ref = rotation.get("reference_doc")
        if ref:
            ref_abs = os.path.join(PLANSYNC_ROOT, ref)
            if os.path.exists(ref_abs):
                add(f"**Reference:** `{ref}` -- rotation design, variety guidance, planting rules")
                add("")

        lines.extend(render_rotation(rotation, date.today()))

    acts = [engine.row_to_dict(r) for r in conn.execute(
        "SELECT * FROM activities WHERE domain_id=? ORDER BY sort_order, trigger_date", (did,))]
    steps_by_act = {}
    for s in conn.execute(
        "SELECT s.* FROM steps s JOIN activities a ON s.activity_id=a.id WHERE a.domain_id=? ORDER BY s.due_date",
        (did,),
    ):
        steps_by_act.setdefault(s["activity_id"], []).append(dict(s))

    def group_label(a):
        return f" [{a['group_name']}]" if a.get("group_name") else ""

    fired = [a for a in acts if a["status"] in ("preparing", "active")]
    add("## In progress (trigger fired)")
    if fired:
        for a in fired:
            add(f"- **{a['name']}**{group_label(a)} -- {a['status']}, fired {str(a.get('trigger_fired') or '?')[:10]}, target {a.get('trigger_date') or '?'}")
            for s in steps_by_act.get(a["id"], []):
                if s["status"] in ("pending", "due"):
                    add(f"  - [ ] {s['name']} -- due {s['due_date'] or 'unscheduled'}{' (OVERDUE)' if s['status'] == 'due' else ''}")
    else:
        add("- none")
    add("")

    names = {a["id"]: a["name"] for a in acts}
    watching = [a for a in acts if a["status"] == "watching"]
    add("## Watching (upcoming)")
    if watching:
        for a in sorted(watching, key=lambda a: a.get("trigger_date") or "9999"):
            date_part = f"est. {a['trigger_date']}" if a.get("trigger_date") else "date TBD"
            add(f"- **{a['name']}**{group_label(a)} -- {date_part} -- {fmt_trigger(a, names)}")
    else:
        add("- none")
    add("")

    add(f"## Completed (last {RECENT_DAYS} days)")
    recent_done = conn.execute(
        "SELECT name, group_name, completed_at FROM activities WHERE domain_id=? AND status IN ('completed','skipped') "
        "AND completed_at >= datetime('now', ?) ORDER BY completed_at DESC",
        (did, f"-{RECENT_DAYS} days"),
    ).fetchall()
    if recent_done:
        for r in recent_done:
            add(f"- {r['name']} -- {str(r['completed_at'])[:10]}")
    else:
        add("- none")
    add("")

    add(f"## Observations (last {RECENT_DAYS} days)")
    obs = conn.execute(
        "SELECT timestamp, new_value FROM activity_log WHERE action='observation' "
        "AND json_extract(new_value, '$.domain_id')=? AND timestamp >= datetime('now', ?) ORDER BY timestamp DESC",
        (did, f"-{RECENT_DAYS} days"),
    ).fetchall()
    if obs:
        for r in obs:
            text = json.loads(r["new_value"]).get("text", "")
            add(f"- {str(r['timestamp'])[:10]}: {text}")
    else:
        add("- none")
    add("")

    add("## Conditions watch")
    conds = conn.execute(
        "SELECT c.*, a.name as activity_name FROM conditions c JOIN activities a ON c.activity_id=a.id "
        "WHERE a.domain_id=? AND a.status='watching'",
        (did,),
    ).fetchall()
    if conds:
        for c in conds:
            d = json.loads(c["definition"]) if isinstance(c["definition"], str) else c["definition"]
            met = "MET" if c["is_met"] else "not met"
            cur = f", currently {c['current_value']}" if c["current_value"] is not None else ""
            add(f"- {c['activity_name']}: {d.get('metric')} {d.get('operator')} {d.get('value')}"
                + (f" x{d.get('sustained_days')}d" if d.get("sustained_days", 1) > 1 else "")
                + f" -- {met}{cur}")
    else:
        add("- none")
    add("")

    add("## Recent weather (last 7 days)")
    weather = conn.execute(
        "SELECT weather_date, temp_high, temp_low, conditions, precipitation FROM weather_log "
        "WHERE location=? AND weather_date >= date('now', '-7 days') ORDER BY weather_date DESC",
        (domain["location"],),
    ).fetchall()
    if weather:
        for w in weather:
            add(f"- {w['weather_date']}: high {w['temp_high']}, low {w['temp_low']}, {w['conditions'] or '?'}"
                + (f", precip {w['precipitation']}\"" if w["precipitation"] else ""))
    else:
        add("- none")
    add("")

    return "\n".join(lines)


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
            content = render_domain(conn, d)
            path = os.path.join(domain_dir, "dossier.md")
            with open(path, "w") as f:
                f.write(content)
        print(f"exported {len(domains)} domain dossiers to {DOMAINS_DIR}/*/dossier.md", file=sys.stderr)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
