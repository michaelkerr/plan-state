#!/usr/bin/env python3
"""Plan-Sync MCP server. Exposes the SQLite plan store as typed tools for Hermes."""

import asyncio
import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/plansync/plansync.db")

server = Server("plansync")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if k.endswith("_json") or k in ("trigger_def", "recurrence", "condition", "definition", "forecast_json", "old_value", "new_value"):
            if isinstance(v, str):
                try:
                    d[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass
    return d


def log_change(conn, item_type, item_id, action, old_value, new_value, source="hermes"):
    conn.execute(
        "INSERT INTO activity_log (item_type, item_id, action, old_value, new_value, source) VALUES (?,?,?,?,?,?)",
        (item_type, item_id, action, json.dumps(old_value), json.dumps(new_value), source),
    )


def cascade_step_dates(conn, activity_id, trigger_date_str):
    if not trigger_date_str:
        return
    trigger_dt = date.fromisoformat(trigger_date_str)
    steps = conn.execute(
        "SELECT id, step_type, lead_days, due_date FROM steps WHERE activity_id=? AND status NOT IN ('completed','skipped')",
        (activity_id,),
    ).fetchall()
    for s in steps:
        if s["step_type"] == "prep":
            new_due = (trigger_dt - timedelta(days=s["lead_days"])).isoformat()
        else:
            new_due = (trigger_dt + timedelta(days=s["lead_days"])).isoformat()
        if new_due != s["due_date"]:
            old_due = s["due_date"]
            conn.execute("UPDATE steps SET due_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_due, s["id"]))
            log_change(conn, "step", s["id"], "date_cascade", {"due_date": old_due}, {"due_date": new_due})
            conn.execute(
                """INSERT OR REPLACE INTO todoist_sync (plan_item_id, plan_item_type, todoist_task_id, todoist_project, last_synced, sync_status)
                   VALUES (?, 'step',
                     COALESCE((SELECT todoist_task_id FROM todoist_sync WHERE plan_item_id=? AND plan_item_type='step'), NULL),
                     COALESCE((SELECT todoist_project FROM todoist_sync WHERE plan_item_id=? AND plan_item_type='step'), NULL),
                     NULL, 'pending_update')""",
                (s["id"], s["id"], s["id"]),
            )


def compute_trigger_date(trigger_def):
    if not trigger_def:
        return None
    if isinstance(trigger_def, str):
        trigger_def = json.loads(trigger_def)
    t = trigger_def.get("type")
    if t == "calendar":
        return trigger_def.get("date")
    if t == "compound":
        for sub in trigger_def.get("conditions", []):
            if sub.get("type") == "calendar":
                d = sub.get("date") or sub.get("after")
                if d:
                    return d
    return None


def ok(data) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(data, default=str, indent=2))]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_domains",
            description="List all domains with activity counts and status summary.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_domain_plan",
            description="Full plan for a domain: activities, steps, conditions, dates.",
            inputSchema={
                "type": "object",
                "properties": {"domain_id": {"type": "string"}},
                "required": ["domain_id"],
            },
        ),
        types.Tool(
            name="create_domain",
            description="Create a new planning domain (e.g. 'Fall Garden', 'Deer Hunting').",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "location": {"type": "string", "description": "Location for weather queries"},
                    "notes": {"type": "string"},
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="create_activity",
            description="Create an activity with optional prep/follow-up steps and trigger conditions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "group_name": {"type": "string", "description": "Optional bundle label within the domain (crop, bed, species). Display only."},
                    "trigger_type": {"type": "string", "enum": ["calendar", "condition", "dependency", "compound"]},
                    "trigger_def": {"type": "object", "description": "Structured trigger definition"},
                    "recurrence": {"type": "object", "description": "Recurrence rule, if cyclical"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "step_type": {"type": "string", "enum": ["prep", "follow_up"]},
                                "lead_days": {"type": "integer"},
                                "condition": {"type": "object"},
                            },
                            "required": ["name", "step_type", "lead_days"],
                        },
                    },
                    "conditions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "condition_type": {"type": "string", "enum": ["temperature", "weather_event", "calendar", "dependency"]},
                                "definition": {"type": "object"},
                            },
                            "required": ["condition_type", "definition"],
                        },
                    },
                },
                "required": ["domain_id", "name", "trigger_type", "trigger_def"],
            },
        ),
        types.Tool(
            name="update_activity",
            description="Update fields on an existing activity. Re-cascades step dates if trigger_date changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "group_name": {"type": "string", "description": "Optional bundle label within the domain (crop, bed, species). Display only."},
                    "status": {"type": "string", "enum": ["watching", "preparing", "active", "completed", "skipped", "deferred"]},
                    "trigger_type": {"type": "string"},
                    "trigger_def": {"type": "object"},
                    "trigger_date": {"type": "string", "format": "date"},
                    "recurrence": {"type": "object"},
                },
                "required": ["activity_id"],
            },
        ),
        types.Tool(
            name="complete_activity",
            description="Mark an activity completed. Cascades follow-up steps and activates dependent activities.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["activity_id"],
            },
        ),
        types.Tool(
            name="defer_activity",
            description="Defer an activity to a new date. Re-cascades all step dates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "new_date": {"type": "string", "format": "date"},
                    "reason": {"type": "string"},
                },
                "required": ["activity_id"],
            },
        ),
        types.Tool(
            name="add_observation",
            description="Record a freeform field observation, optionally linking to affected activities.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_id": {"type": "string"},
                    "observation_text": {"type": "string"},
                    "affects_activities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Activity IDs this observation might affect",
                    },
                },
                "required": ["domain_id", "observation_text"],
            },
        ),
        types.Tool(
            name="get_upcoming",
            description="Cross-domain view of everything due or approaching trigger in the next N days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "default": 14},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="get_weather_current",
            description="Latest weather data and 7-day forecast from the weather log for a location.",
            inputSchema={
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        ),
        types.Tool(
            name="load_domain",
            description="Bulk-load a complete domain definition (domain + all activities, steps, conditions) in one atomic operation. Validates the definition, resolves activity_ref dependencies by name, and rolls back on any error.",
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Complete domain definition conforming to domain_schema.json",
                    },
                },
                "required": ["definition"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    conn = get_db()
    try:
        if name == "get_domains":
            return _get_domains(conn)
        elif name == "get_domain_plan":
            return _get_domain_plan(conn, arguments["domain_id"])
        elif name == "create_domain":
            return _create_domain(conn, arguments)
        elif name == "create_activity":
            return _create_activity(conn, arguments)
        elif name == "update_activity":
            return _update_activity(conn, arguments)
        elif name == "complete_activity":
            return _complete_activity(conn, arguments)
        elif name == "defer_activity":
            return _defer_activity(conn, arguments)
        elif name == "add_observation":
            return _add_observation(conn, arguments)
        elif name == "get_upcoming":
            return _get_upcoming(conn, arguments.get("days_ahead", 14))
        elif name == "get_weather_current":
            return _get_weather_current(conn, arguments["location"])
        elif name == "load_domain":
            return _load_domain(conn, arguments)
        else:
            return ok({"error": f"Unknown tool: {name}"})
    finally:
        conn.close()


def _get_domains(conn) -> list[types.TextContent]:
    domains = conn.execute("SELECT * FROM domains ORDER BY name").fetchall()
    result = []
    for d in domains:
        d = row_to_dict(d)
        counts = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM activities WHERE domain_id=? GROUP BY status",
            (d["id"],),
        ).fetchall()
        d["activity_counts"] = {r["status"]: r["cnt"] for r in counts}
        d["total_activities"] = sum(d["activity_counts"].values())
        result.append(d)
    return ok(result)


def _get_domain_plan(conn, domain_id) -> list[types.TextContent]:
    domain = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
    if not domain:
        return ok({"error": f"Domain {domain_id} not found"})
    domain = row_to_dict(domain)

    activities = conn.execute(
        "SELECT * FROM activities WHERE domain_id=? ORDER BY sort_order, trigger_date",
        (domain_id,),
    ).fetchall()

    domain["activities"] = []
    for a in activities:
        a = row_to_dict(a)
        a["steps"] = [
            row_to_dict(s)
            for s in conn.execute("SELECT * FROM steps WHERE activity_id=? ORDER BY sort_order, due_date", (a["id"],)).fetchall()
        ]
        a["conditions"] = [
            row_to_dict(c)
            for c in conn.execute("SELECT * FROM conditions WHERE activity_id=?", (a["id"],)).fetchall()
        ]
        domain["activities"].append(a)

    return ok(domain)


def _create_domain(conn, args) -> list[types.TextContent]:
    did = new_id()
    conn.execute(
        "INSERT INTO domains (id, name, location, notes) VALUES (?,?,?,?)",
        (did, args["name"], args.get("location"), args.get("notes")),
    )
    log_change(conn, "domain", did, "created", None, {"name": args["name"]})
    conn.commit()
    return ok({"id": did, "name": args["name"], "location": args.get("location")})


def _load_domain(conn, args) -> list[types.TextContent]:
    defn = args.get("definition")
    if not defn:
        return ok({"error": "Missing 'definition' field"})

    errors = _validate_domain_definition(defn)
    if errors:
        return ok({"error": "Validation failed", "details": errors})

    name = defn["name"]
    existing = conn.execute("SELECT id FROM domains WHERE name=?", (name,)).fetchone()
    if existing:
        return ok({"error": f"Domain '{name}' already exists (id: {existing['id']})"})

    try:
        did = new_id()
        conn.execute(
            "INSERT INTO domains (id, name, location, notes) VALUES (?,?,?,?)",
            (did, name, defn.get("location"), defn.get("notes")),
        )
        log_change(conn, "domain", did, "created", None, {"name": name})

        name_to_id = {}
        activity_results = []

        for i, act_def in enumerate(defn["activities"]):
            aid = new_id()
            name_to_id[act_def["name"]] = aid

        for i, act_def in enumerate(defn["activities"]):
            aid = name_to_id[act_def["name"]]
            trigger_def = _resolve_refs(act_def["trigger_def"], name_to_id)
            if isinstance(trigger_def, dict) and trigger_def.get("_error"):
                raise ValueError(trigger_def["_error"])

            trigger_def_str = json.dumps(trigger_def)
            trigger_date = compute_trigger_date(trigger_def)

            conn.execute(
                """INSERT INTO activities (id, domain_id, name, description, group_name, trigger_type, trigger_def, trigger_date, recurrence, sort_order)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    aid, did, act_def["name"], act_def.get("description"), act_def.get("group_name"),
                    act_def["trigger_type"], trigger_def_str, trigger_date,
                    json.dumps(act_def["recurrence"]) if act_def.get("recurrence") else None,
                    act_def.get("sort_order", i),
                ),
            )
            log_change(conn, "activity", aid, "created", None, {"name": act_def["name"], "trigger_type": act_def["trigger_type"]})

            created_steps = []
            for j, step_def in enumerate(act_def.get("steps", [])):
                sid = new_id()
                due = None
                if trigger_date:
                    td = date.fromisoformat(trigger_date)
                    if step_def["step_type"] == "prep":
                        due = (td - timedelta(days=step_def["lead_days"])).isoformat()
                    else:
                        due = (td + timedelta(days=step_def["lead_days"])).isoformat()
                conn.execute(
                    """INSERT INTO steps (id, activity_id, name, description, step_type, lead_days, due_date, condition, sort_order)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        sid, aid, step_def["name"], step_def.get("description"),
                        step_def["step_type"], step_def["lead_days"], due,
                        json.dumps(step_def["condition"]) if step_def.get("condition") else None,
                        j,
                    ),
                )
                created_steps.append({"id": sid, "name": step_def["name"], "due_date": due})

            for cond_def in act_def.get("conditions", []):
                cid = new_id()
                conn.execute(
                    "INSERT INTO conditions (id, activity_id, condition_type, definition) VALUES (?,?,?,?)",
                    (cid, aid, cond_def["condition_type"], json.dumps(cond_def["definition"])),
                )

            activity_results.append({
                "id": aid,
                "name": act_def["name"],
                "group_name": act_def.get("group_name"),
                "trigger_type": act_def["trigger_type"],
                "trigger_date": trigger_date,
                "status": "watching",
                "steps": created_steps,
            })

        conn.commit()
        return ok({
            "id": did,
            "name": name,
            "location": defn.get("location"),
            "activities": activity_results,
        })

    except (ValueError, sqlite3.Error) as e:
        conn.rollback()
        return ok({"error": str(e)})


def _validate_domain_definition(defn):
    errors = []
    if not isinstance(defn, dict):
        return [{"path": "", "error": "Definition must be an object"}]
    if "name" not in defn:
        errors.append({"path": "name", "error": "Required field missing"})
    if "activities" not in defn:
        errors.append({"path": "activities", "error": "Required field missing"})
    elif not isinstance(defn["activities"], list) or len(defn["activities"]) == 0:
        errors.append({"path": "activities", "error": "Must be a non-empty array"})
    else:
        valid_trigger_types = {"calendar", "condition", "dependency", "compound"}
        valid_step_types = {"prep", "follow_up"}
        activity_names = set()
        for i, act in enumerate(defn["activities"]):
            prefix = f"activities[{i}]"
            if not isinstance(act, dict):
                errors.append({"path": prefix, "error": "Must be an object"})
                continue
            if "name" not in act:
                errors.append({"path": f"{prefix}.name", "error": "Required field missing"})
            elif act["name"] in activity_names:
                errors.append({"path": f"{prefix}.name", "error": f"Duplicate activity name: {act['name']}"})
            else:
                activity_names.add(act["name"])
            if "trigger_type" not in act:
                errors.append({"path": f"{prefix}.trigger_type", "error": "Required field missing"})
            elif act["trigger_type"] not in valid_trigger_types:
                errors.append({"path": f"{prefix}.trigger_type", "error": f"Invalid trigger type: {act['trigger_type']}"})
            if "trigger_def" not in act:
                errors.append({"path": f"{prefix}.trigger_def", "error": "Required field missing"})
            for j, step in enumerate(act.get("steps", [])):
                sp = f"{prefix}.steps[{j}]"
                if "name" not in step:
                    errors.append({"path": f"{sp}.name", "error": "Required field missing"})
                if "step_type" not in step:
                    errors.append({"path": f"{sp}.step_type", "error": "Required field missing"})
                elif step["step_type"] not in valid_step_types:
                    errors.append({"path": f"{sp}.step_type", "error": f"Invalid step type: {step['step_type']}"})
                if "lead_days" not in step:
                    errors.append({"path": f"{sp}.lead_days", "error": "Required field missing"})
                elif not isinstance(step["lead_days"], int) or step["lead_days"] < 0:
                    errors.append({"path": f"{sp}.lead_days", "error": "Must be a non-negative integer"})

        for i, act in enumerate(defn["activities"]):
            tdef = act.get("trigger_def", {})
            _validate_dependency_refs(tdef, activity_names, f"activities[{i}].trigger_def", errors)

    return errors


def _validate_dependency_refs(tdef, activity_names, path, errors):
    if not isinstance(tdef, dict):
        return
    if tdef.get("type") == "dependency" and "activity_ref" in tdef:
        if tdef["activity_ref"] not in activity_names:
            errors.append({"path": f"{path}.activity_ref", "error": f"References unknown activity: {tdef['activity_ref']}"})
    if tdef.get("type") == "compound":
        for j, sub in enumerate(tdef.get("conditions", [])):
            _validate_dependency_refs(sub, activity_names, f"{path}.conditions[{j}]", errors)


def _resolve_refs(tdef, name_to_id):
    if not isinstance(tdef, dict):
        return tdef
    result = dict(tdef)
    if result.get("type") == "dependency" and "activity_ref" in result:
        ref_name = result.pop("activity_ref")
        if ref_name not in name_to_id:
            return {"_error": f"Cannot resolve activity_ref '{ref_name}': not found in this domain definition"}
        result["activity_id"] = name_to_id[ref_name]
    if result.get("type") == "compound" and "conditions" in result:
        resolved_subs = []
        for sub in result["conditions"]:
            resolved = _resolve_refs(sub, name_to_id)
            if isinstance(resolved, dict) and resolved.get("_error"):
                return resolved
            resolved_subs.append(resolved)
        result["conditions"] = resolved_subs
    return result


def _create_activity(conn, args) -> list[types.TextContent]:
    aid = new_id()
    trigger_def = args["trigger_def"]
    trigger_def_str = json.dumps(trigger_def) if isinstance(trigger_def, dict) else trigger_def
    trigger_date = compute_trigger_date(trigger_def)

    conn.execute(
        """INSERT INTO activities (id, domain_id, name, description, group_name, trigger_type, trigger_def, trigger_date, recurrence, sort_order)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            aid,
            args["domain_id"],
            args["name"],
            args.get("description"),
            args.get("group_name"),
            args["trigger_type"],
            trigger_def_str,
            trigger_date,
            json.dumps(args["recurrence"]) if args.get("recurrence") else None,
            args.get("sort_order", 0),
        ),
    )
    log_change(conn, "activity", aid, "created", None, {"name": args["name"], "trigger_type": args["trigger_type"]})

    created_steps = []
    for i, step in enumerate(args.get("steps", [])):
        sid = new_id()
        due = None
        if trigger_date:
            td = date.fromisoformat(trigger_date)
            if step["step_type"] == "prep":
                due = (td - timedelta(days=step["lead_days"])).isoformat()
            else:
                due = (td + timedelta(days=step["lead_days"])).isoformat()
        conn.execute(
            """INSERT INTO steps (id, activity_id, name, description, step_type, lead_days, due_date, condition, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                sid, aid, step["name"], step.get("description"),
                step["step_type"], step["lead_days"], due,
                json.dumps(step["condition"]) if step.get("condition") else None,
                i,
            ),
        )
        created_steps.append({"id": sid, "name": step["name"], "due_date": due})

    for cond in args.get("conditions", []):
        cid = new_id()
        conn.execute(
            "INSERT INTO conditions (id, activity_id, condition_type, definition) VALUES (?,?,?,?)",
            (cid, aid, cond["condition_type"], json.dumps(cond["definition"])),
        )

    conn.commit()
    return ok({
        "id": aid,
        "name": args["name"],
        "trigger_date": trigger_date,
        "status": "watching",
        "steps": created_steps,
    })


def _update_activity(conn, args) -> list[types.TextContent]:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return ok({"error": f"Activity {aid} not found"})
    current = row_to_dict(current)

    updatable = ["name", "description", "group_name", "status", "trigger_type", "trigger_def", "trigger_date", "recurrence"]
    sets, vals, changes = [], [], {}
    for field in updatable:
        if field in args and args[field] is not None:
            val = args[field]
            if field in ("trigger_def", "recurrence") and isinstance(val, dict):
                val = json.dumps(val)
            sets.append(f"{field}=?")
            vals.append(val)
            changes[field] = {"old": current.get(field), "new": args[field]}

    if not sets:
        return ok({"error": "No fields to update"})

    sets.append("updated_at=CURRENT_TIMESTAMP")
    vals.append(aid)
    conn.execute(f"UPDATE activities SET {', '.join(sets)} WHERE id=?", vals)

    if "trigger_date" in args and args["trigger_date"] != current.get("trigger_date"):
        cascade_step_dates(conn, aid, args["trigger_date"])
    elif "trigger_def" in args:
        new_td = compute_trigger_date(args["trigger_def"])
        if new_td and new_td != current.get("trigger_date"):
            conn.execute("UPDATE activities SET trigger_date=? WHERE id=?", (new_td, aid))
            cascade_step_dates(conn, aid, new_td)

    if "status" in changes:
        log_change(conn, "activity", aid, "status_change", {"status": changes["status"]["old"]}, {"status": changes["status"]["new"]})
    else:
        log_change(conn, "activity", aid, "manual_update", {k: v["old"] for k, v in changes.items()}, {k: v["new"] for k, v in changes.items()})

    conn.commit()

    updated = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    updated = row_to_dict(updated)
    updated["steps"] = [
        row_to_dict(s)
        for s in conn.execute("SELECT * FROM steps WHERE activity_id=? ORDER BY sort_order, due_date", (aid,)).fetchall()
    ]
    return ok(updated)


def _complete_activity(conn, args) -> list[types.TextContent]:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return ok({"error": f"Activity {aid} not found"})

    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE activities SET status='completed', completed_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (now, aid),
    )
    log_change(conn, "activity", aid, "status_change", {"status": current["status"]}, {"status": "completed", "notes": args.get("notes")})

    conn.execute(
        "UPDATE steps SET status='completed', completed_at=? WHERE activity_id=? AND step_type='prep' AND status='pending'",
        (now, aid),
    )

    follow_ups = conn.execute(
        "SELECT id, name, lead_days FROM steps WHERE activity_id=? AND step_type='follow_up' AND status='pending'",
        (aid,),
    ).fetchall()
    cascaded = []
    for fu in follow_ups:
        due = (date.today() + timedelta(days=fu["lead_days"])).isoformat()
        conn.execute("UPDATE steps SET due_date=?, status='due', updated_at=CURRENT_TIMESTAMP WHERE id=?", (due, fu["id"]))
        cascaded.append({"id": fu["id"], "name": fu["name"], "due_date": due})

    dependents = conn.execute(
        "SELECT id, name, trigger_def FROM activities WHERE trigger_type='dependency' AND status='watching'",
    ).fetchall()
    activated = []
    for dep in dependents:
        tdef = json.loads(dep["trigger_def"]) if isinstance(dep["trigger_def"], str) else dep["trigger_def"]
        if tdef.get("activity_id") == aid and tdef.get("event") == "completed":
            offset = tdef.get("offset_days", 0)
            new_trigger = (date.today() + timedelta(days=offset)).isoformat()
            conn.execute(
                "UPDATE activities SET status='preparing', trigger_date=?, trigger_fired=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_trigger, now, dep["id"]),
            )
            cascade_step_dates(conn, dep["id"], new_trigger)
            log_change(conn, "activity", dep["id"], "trigger_fire", {"status": "watching"}, {"status": "preparing", "trigger_date": new_trigger})
            activated.append({"id": dep["id"], "name": dep["name"], "trigger_date": new_trigger})

    conn.execute(
        """INSERT OR REPLACE INTO todoist_sync (plan_item_id, plan_item_type, todoist_task_id, todoist_project, last_synced, sync_status)
           VALUES (?, 'activity',
             COALESCE((SELECT todoist_task_id FROM todoist_sync WHERE plan_item_id=? AND plan_item_type='activity'), NULL),
             COALESCE((SELECT todoist_project FROM todoist_sync WHERE plan_item_id=? AND plan_item_type='activity'), NULL),
             NULL, 'pending_close')""",
        (aid, aid, aid),
    )

    conn.commit()
    return ok({
        "completed": aid,
        "follow_up_steps_due": cascaded,
        "dependent_activities_activated": activated,
    })


def _defer_activity(conn, args) -> list[types.TextContent]:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return ok({"error": f"Activity {aid} not found"})

    new_date = args.get("new_date")
    reason = args.get("reason", "")

    updates = ["status='deferred'", "updated_at=CURRENT_TIMESTAMP"]
    vals = []
    if new_date:
        updates.append("trigger_date=?")
        vals.append(new_date)
    vals.append(aid)

    conn.execute(f"UPDATE activities SET {', '.join(updates)} WHERE id=?", vals)
    log_change(
        conn, "activity", aid, "status_change",
        {"status": current["status"], "trigger_date": current["trigger_date"]},
        {"status": "deferred", "trigger_date": new_date, "reason": reason},
    )

    if new_date:
        cascade_step_dates(conn, aid, new_date)

    conn.commit()

    updated = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    updated = row_to_dict(updated)
    updated["steps"] = [
        row_to_dict(s)
        for s in conn.execute("SELECT * FROM steps WHERE activity_id=? ORDER BY sort_order, due_date", (aid,)).fetchall()
    ]
    return ok(updated)


def _add_observation(conn, args) -> list[types.TextContent]:
    oid = new_id()
    log_change(
        conn, "activity", oid, "observation",
        None,
        {
            "domain_id": args["domain_id"],
            "text": args["observation_text"],
            "affects": args.get("affects_activities", []),
        },
    )

    affected = []
    for aid in args.get("affects_activities", []):
        a = conn.execute("SELECT id, name FROM activities WHERE id=?", (aid,)).fetchone()
        if a:
            affected.append({"id": a["id"], "name": a["name"]})

    conn.commit()
    return ok({
        "observation_id": oid,
        "recorded": True,
        "affected_activities": affected,
    })


def _get_upcoming(conn, days_ahead) -> list[types.TextContent]:
    cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
    today_str = date.today().isoformat()

    activities = conn.execute(
        """SELECT a.*, d.name as domain_name FROM activities a
           JOIN domains d ON a.domain_id = d.id
           WHERE a.status IN ('watching','preparing','active')
             AND (a.trigger_date <= ? OR a.trigger_date IS NULL)
           ORDER BY a.trigger_date NULLS LAST, a.sort_order""",
        (cutoff,),
    ).fetchall()

    result = []
    for a in activities:
        a = row_to_dict(a)
        a["steps"] = [
            row_to_dict(s)
            for s in conn.execute(
                "SELECT * FROM steps WHERE activity_id=? AND status IN ('pending','due') AND (due_date <= ? OR due_date IS NULL) ORDER BY due_date",
                (a["id"], cutoff),
            ).fetchall()
        ]
        overdue_steps = [s for s in a["steps"] if s.get("due_date") and s["due_date"] < today_str]
        a["has_overdue"] = len(overdue_steps) > 0
        result.append(a)

    return ok({"today": today_str, "cutoff": cutoff, "items": result})


def _get_weather_current(conn, location) -> list[types.TextContent]:
    latest = conn.execute(
        "SELECT * FROM weather_log WHERE location=? ORDER BY recorded_at DESC LIMIT 1",
        (location,),
    ).fetchone()

    if not latest:
        return ok({"location": location, "error": "No weather data recorded for this location"})

    history = conn.execute(
        "SELECT recorded_at, temp_high, temp_low, soil_temp, conditions, precipitation FROM weather_log WHERE location=? ORDER BY recorded_at DESC LIMIT 7",
        (location,),
    ).fetchall()

    result = row_to_dict(latest)
    result["recent_history"] = [row_to_dict(h) for h in history]
    return ok(result)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
