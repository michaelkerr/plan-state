#!/usr/bin/env python3
"""Plan-Sync MCP server. Exposes the SQLite plan store as typed tools for Hermes."""

import asyncio
import json
import os
import sqlite3
import sys
import uuid
from datetime import date, timedelta

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plansync.engine import (  # noqa: E402
    cascade_step_dates,
    compute_trigger_date,
    defer_trigger_def,
    derive_conditions,
    get_actionable_items,
    get_db,
    get_open_activities,
    log_change,
    new_batch_id,
    react,
    row_to_dict,
    step_due_date,
    transition,
)

server = Server("plansync")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


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
            name="update_activity",
            description="Update fields on an existing activity. Re-cascades step dates if trigger_date changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "group_name": {"type": "string", "description": "Optional bundle label within the domain (crop, bed, species). Display only."},
                    "status": {"type": "string", "enum": ["watching", "preparing", "active", "completed", "skipped"]},
                    "trigger_type": {"type": "string"},
                    "trigger_def": {"type": "object"},
                    "trigger_date": {"type": "string", "format": "date"},
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
            description="Defer an activity to a new date: moves the trigger (date or earliest-date gate), returns it to 'watching' so the cron re-fires on the new date, and re-cascades all step dates. Always include a reason.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "new_date": {"type": "string", "format": "date"},
                    "reason": {"type": "string"},
                },
                "required": ["activity_id", "new_date"],
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
            name="add_activities",
            description="Add one or more activities (with steps and conditions) to an EXISTING domain. Same activity format as load_domain. Atomic: all created or none. Dependency activity_ref names resolve against both the new batch and activities already in the domain.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_id": {"type": "string"},
                    "activities": {
                        "type": "array",
                        "minItems": 1,
                        "description": "Activity definitions conforming to the activity schema in domain_schema.json",
                        "items": {"type": "object"},
                    },
                },
                "required": ["domain_id", "activities"],
            },
        ),
        types.Tool(
            name="delete_activity",
            description="Remove an activity. Default is a soft delete: activity and its open steps move to 'skipped' (reversible, disappears from actionable views). permanent=true deletes the activity, its steps, conditions, and log entries with no trace -- use only when the user explicitly wants it gone for good.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "permanent": {"type": "boolean", "default": False},
                },
                "required": ["activity_id"],
            },
        ),
        types.Tool(
            name="update_step",
            description="Update fields on an existing step. Changing status to 'completed' sets completed_at; changing lead_days or step_type re-derives due_date from the parent activity's trigger_date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["pending", "due", "completed", "skipped"]},
                    "lead_days": {"type": "integer", "minimum": 0},
                    "step_type": {"type": "string", "enum": ["prep", "follow_up"]},
                },
                "required": ["step_id"],
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
        elif name == "update_activity":
            return _update_activity(conn, arguments)
        elif name == "update_step":
            return _update_step(conn, arguments)
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
        elif name == "add_activities":
            return _add_activities(conn, arguments)
        elif name == "delete_activity":
            return _delete_activity(conn, arguments)
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
            activity_results.append(_insert_activity(conn, did, aid, act_def, name_to_id, default_sort=i))

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


def _insert_activity(conn, domain_id, aid, act_def, name_to_id, default_sort):
    """Insert one activity with its steps and conditions. Raises ValueError on
    unresolvable dependency refs; caller owns the transaction.

    No trigger = decided work: starts 'active' with no trigger_date, no
    conditions, NULL step due dates (set via update_step or when a
    trigger_def is added later)."""
    trigger_def = act_def.get("trigger_def")
    if trigger_def is not None:
        trigger_def = _resolve_refs(trigger_def, name_to_id)
        if isinstance(trigger_def, dict) and trigger_def.get("_error"):
            raise ValueError(trigger_def["_error"])

    trigger_def_str = json.dumps(trigger_def) if trigger_def is not None else None
    trigger_date = compute_trigger_date(trigger_def) if trigger_def is not None else None
    status = "watching" if trigger_def is not None else "active"

    conn.execute(
        """INSERT INTO activities (id, domain_id, name, description, group_name, status, trigger_type, trigger_def, trigger_date, sort_order)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            aid, domain_id, act_def["name"], act_def.get("description"), act_def.get("group_name"),
            status, act_def.get("trigger_type"), trigger_def_str, trigger_date,
            act_def.get("sort_order", default_sort),
        ),
    )
    log_change(conn, "activity", aid, "created", None,
               {"name": act_def["name"], "trigger_type": act_def.get("trigger_type"), "status": status})

    created_steps = []
    for j, step_def in enumerate(act_def.get("steps", [])):
        sid = new_id()
        due = step_due_date(trigger_date, step_def["step_type"], step_def["lead_days"])
        conn.execute(
            """INSERT INTO steps (id, activity_id, name, description, step_type, lead_days, due_date, sort_order)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                sid, aid, step_def["name"], step_def.get("description"),
                step_def["step_type"], step_def["lead_days"], due, j,
            ),
        )
        created_steps.append({"id": sid, "name": step_def["name"], "due_date": due})

    for cond_def in derive_conditions(trigger_def) if trigger_def is not None else []:
        cid = new_id()
        conn.execute(
            "INSERT INTO conditions (id, activity_id, condition_type, definition) VALUES (?,?,?,?)",
            (cid, aid, cond_def["condition_type"], json.dumps(cond_def["definition"])),
        )

    return {
        "id": aid,
        "name": act_def["name"],
        "group_name": act_def.get("group_name"),
        "trigger_type": act_def.get("trigger_type"),
        "trigger_date": trigger_date,
        "status": status,
        "steps": created_steps,
    }


def _add_activities(conn, args) -> list[types.TextContent]:
    domain_id = args.get("domain_id")
    activities = args.get("activities")

    domain = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
    if not domain:
        return ok({"error": f"Domain {domain_id} not found"})
    if not isinstance(activities, list) or len(activities) == 0:
        return ok({"error": "activities must be a non-empty array"})

    existing = conn.execute(
        "SELECT id, name, sort_order FROM activities WHERE domain_id=?", (domain_id,)
    ).fetchall()
    existing_names = {r["name"] for r in existing}

    errors = _validate_activities(activities, [], existing_names)
    if errors:
        return ok({"error": "Validation failed", "details": errors})

    name_to_id = {r["name"]: r["id"] for r in existing}
    for act_def in activities:
        name_to_id[act_def["name"]] = new_id()
    max_sort = max((r["sort_order"] or 0 for r in existing), default=0)

    try:
        results = []
        for i, act_def in enumerate(activities):
            aid = name_to_id[act_def["name"]]
            results.append(_insert_activity(conn, domain_id, aid, act_def, name_to_id, default_sort=max_sort + i + 1))
        conn.commit()
        return ok({
            "domain_id": domain_id,
            "domain_name": domain["name"],
            "activities": results,
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
        _validate_activities(defn["activities"], errors)

    return errors


def _validate_activities(activities, errors, existing_names=frozenset()):
    """Validate a batch of activity definitions. existing_names are activities
    already in the domain: duplicates against them are rejected, but dependency
    refs may resolve to them."""
    valid_trigger_types = {"calendar", "condition", "dependency", "compound"}
    valid_step_types = {"prep", "follow_up"}
    batch_names = set()
    for i, act in enumerate(activities):
        prefix = f"activities[{i}]"
        if not isinstance(act, dict):
            errors.append({"path": prefix, "error": "Must be an object"})
            continue
        if "conditions" in act:
            errors.append({
                "path": f"{prefix}.conditions",
                "error": "Explicit conditions arrays are no longer accepted; conditions rows are derived automatically from condition-type leaves in trigger_def. Remove this field.",
            })
        if "recurrence" in act:
            errors.append({
                "path": f"{prefix}.recurrence",
                "error": "recurrence is not supported (it was never evaluated). Annual plans are re-authored each season via a planning conversation. Remove this field.",
            })
        if "name" not in act:
            errors.append({"path": f"{prefix}.name", "error": "Required field missing"})
        elif act["name"] in batch_names or act["name"] in existing_names:
            errors.append({"path": f"{prefix}.name", "error": f"Duplicate activity name: {act['name']}"})
        else:
            batch_names.add(act["name"])
        # Triggers are optional (Step 42): an activity without one is decided
        # work and starts 'active'. But trigger_type and trigger_def come as a
        # pair -- one without the other is an authoring mistake.
        has_type, has_def = "trigger_type" in act, "trigger_def" in act
        if has_type and act["trigger_type"] not in valid_trigger_types:
            errors.append({"path": f"{prefix}.trigger_type", "error": f"Invalid trigger type: {act['trigger_type']}"})
        if has_type and not has_def:
            errors.append({"path": f"{prefix}.trigger_def", "error": "trigger_type given without trigger_def; provide both or neither (no trigger = immediately active work)"})
        if has_def and not has_type:
            errors.append({"path": f"{prefix}.trigger_type", "error": "trigger_def given without trigger_type; provide both or neither (no trigger = immediately active work)"})
        for j, step in enumerate(act.get("steps", [])):
            sp = f"{prefix}.steps[{j}]"
            if "condition" in step:
                errors.append({
                    "path": f"{sp}.condition",
                    "error": "Step conditions are not supported (they were never evaluated). If this step needs its own trigger, make it an activity. Remove this field.",
                })
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

    ref_names = batch_names | set(existing_names)
    for i, act in enumerate(activities):
        if isinstance(act, dict):
            tdef = act.get("trigger_def", {})
            _validate_dependency_refs(tdef, ref_names, f"activities[{i}].trigger_def", errors)
            _validate_condition_metrics(tdef, f"activities[{i}].trigger_def", errors)

    return errors


VALID_METRICS = {"daily_high", "daily_low", "temp_high", "temp_low"}


def _validate_condition_metrics(tdef, path, errors):
    if not isinstance(tdef, dict):
        return
    if tdef.get("type") == "condition":
        for j, clause in enumerate(tdef.get("all", [])):
            metric = clause.get("metric") if isinstance(clause, dict) else None
            if metric == "soil_temp":
                errors.append({
                    "path": f"{path}.all[{j}].metric",
                    "error": "soil_temp is not available (no data source supplies it) -- use daily_high as a proxy",
                })
            elif metric not in VALID_METRICS:
                errors.append({
                    "path": f"{path}.all[{j}].metric",
                    "error": f"Unknown metric '{metric}'. Valid metrics: daily_high, daily_low, temp_high, temp_low",
                })
    if tdef.get("type") == "compound":
        for j, sub in enumerate(tdef.get("conditions", [])):
            _validate_condition_metrics(sub, f"{path}.conditions[{j}]", errors)


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
            return {"_error": f"Cannot resolve activity_ref '{ref_name}': no activity with that name in this domain"}
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


def _update_activity(conn, args) -> list[types.TextContent]:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return ok({"error": f"Activity {aid} not found"})
    current = row_to_dict(current)

    updatable = ["name", "description", "group_name", "status", "trigger_type", "trigger_def", "trigger_date"]
    sets, vals, changes = [], [], {}
    for field in updatable:
        if field in args and args[field] is not None:
            val = args[field]
            if field == "trigger_def" and isinstance(val, dict):
                val = json.dumps(val)
            sets.append(f"{field}=?")
            vals.append(val)
            changes[field] = {"old": current.get(field), "new": args[field]}

    if not sets:
        return ok({"error": "No fields to update"})

    sets.append("updated_at=CURRENT_TIMESTAMP")
    vals.append(aid)
    conn.execute(f"UPDATE activities SET {', '.join(sets)} WHERE id=?", vals)

    if "trigger_def" in changes:
        # trigger_def is the source of truth: rebuild the derived conditions cache
        conn.execute("DELETE FROM conditions WHERE activity_id=?", (aid,))
        for cond_def in derive_conditions(args["trigger_def"]):
            conn.execute(
                "INSERT INTO conditions (id, activity_id, condition_type, definition) VALUES (?,?,?,?)",
                (new_id(), aid, cond_def["condition_type"], json.dumps(cond_def["definition"])),
            )
        # Decided work gaining a trigger goes back under condition watching
        if current.get("trigger_def") is None and current.get("status") == "active" \
                and "status" not in changes:
            transition(conn, "activity", aid, "watch")

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


def _step_status_event(current, desired):
    """Map a requested step status to the state-machine event that reaches it.

    Returns (event, context) or (None, None) when no transition exists."""
    named = {
        ("pending", "completed"): "complete",
        ("due", "completed"): "complete",
        ("pending", "due"): "promote",
        ("pending", "skipped"): "skip",
        ("due", "skipped"): "skip",
        ("completed", "pending"): "uncomplete",
    }
    if (current, desired) in named:
        return named[(current, desired)], {}
    if current in ("completed", "skipped"):
        return "revert", {"to_status": desired}
    return None, None


def _update_step(conn, args) -> list[types.TextContent]:
    sid = args["step_id"]
    current = conn.execute("SELECT * FROM steps WHERE id=?", (sid,)).fetchone()
    if not current:
        return ok({"error": f"Step {sid} not found"})
    current = row_to_dict(current)

    updatable = ["name", "description", "lead_days", "step_type"]
    sets, vals, changes = [], [], {}
    for field in updatable:
        if field in args and args[field] is not None:
            val = args[field]
            sets.append(f"{field}=?")
            vals.append(val)
            changes[field] = {"old": current.get(field), "new": val}

    desired_status = args.get("status")
    if not sets and desired_status is None:
        return ok({"error": "No fields to update"})

    batch = new_batch_id()

    if sets:
        # Re-derive due_date if lead_days or step_type changed
        if "lead_days" in changes or "step_type" in changes:
            activity = conn.execute(
                "SELECT trigger_date FROM activities WHERE id=?", (current["activity_id"],)
            ).fetchone()
            if activity and activity["trigger_date"]:
                new_step_type = args.get("step_type", current["step_type"])
                new_lead_days = args.get("lead_days", current["lead_days"])
                new_due = step_due_date(activity["trigger_date"], new_step_type, new_lead_days)
                sets.append("due_date=?")
                vals.append(new_due)

        sets.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(sid)
        conn.execute(f"UPDATE steps SET {', '.join(sets)} WHERE id=?", vals)
        log_change(conn, "step", sid, "manual_update",
                   {k: v["old"] for k, v in changes.items()},
                   {k: v["new"] for k, v in changes.items()},
                   batch_id=batch)

    if desired_status is not None and desired_status != current["status"]:
        event, context = _step_status_event(current["status"], desired_status)
        if event is None:
            return ok({"error": f"cannot move step {sid} from '{current['status']}' "
                                f"to '{desired_status}': no such transition"})
        context["batch_id"] = batch
        try:
            transition(conn, "step", sid, event, context)
        except ValueError as e:
            return ok({"error": str(e)})

    conn.commit()

    updated = conn.execute("SELECT * FROM steps WHERE id=?", (sid,)).fetchone()
    updated = row_to_dict(updated)
    # Include parent context so the caller knows what activity this belongs to
    activity = conn.execute(
        "SELECT id, name, group_name FROM activities WHERE id=?",
        (updated["activity_id"],),
    ).fetchone()
    if activity:
        updated["activity_name"] = activity["name"]
        updated["activity_group"] = activity["group_name"]
    return ok(updated)


def _complete_activity(conn, args) -> list[types.TextContent]:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return ok({"error": f"Activity {aid} not found"})

    batch = new_batch_id()
    context = {"batch_id": batch}
    if args.get("notes"):
        context["extra"] = {"notes": args["notes"]}
    try:
        events = transition(conn, "activity", aid, "complete", context)
    except ValueError as e:
        return ok({"error": str(e)})

    result = react(conn, events, batch)
    conn.commit()
    return ok({
        "completed": aid,
        "batch_id": batch,
        "prep_steps_completed": result["steps_completed"],
        "follow_up_steps_due": result["follow_ups_promoted"],
        "dependent_activities_activated": result["dependencies_fired"],
    })


def _defer_activity(conn, args) -> list[types.TextContent]:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return ok({"error": f"Activity {aid} not found"})

    new_date = args.get("new_date")
    reason = args.get("reason", "")
    if not new_date:
        return ok({"error": "new_date is required: deferral moves the trigger date (there is no 'deferred' status)"})

    # Deferral is a date move, not a status: the activity returns to 'watching'
    # so the cron re-fires it on the new date (evaluate_triggers only scans
    # 'watching'; a fired activity being deferred needs its trigger_fired reset).
    # trigger_def must move too -- _check_trigger fires from it, not trigger_date.
    batch = new_batch_id()
    try:
        transition(conn, "activity", aid, "defer", {"batch_id": batch})
    except ValueError as e:
        return ok({"error": str(e)})

    old_tdef = row_to_dict(current)["trigger_def"]
    new_tdef = defer_trigger_def(old_tdef, new_date)
    conn.execute(
        "UPDATE activities SET trigger_fired=NULL, trigger_date=?, trigger_def=?, trigger_type=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (new_date, json.dumps(new_tdef), new_tdef["type"], aid),
    )
    log_change(
        conn, "activity", aid, "manual_update",
        {"trigger_date": current["trigger_date"], "trigger_def": old_tdef},
        {"trigger_date": new_date, "trigger_def": new_tdef, "reason": reason},
        batch_id=batch,
    )

    cascade_step_dates(conn, aid, new_date, batch_id=batch)

    conn.commit()

    updated = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    updated = row_to_dict(updated)
    updated["steps"] = [
        row_to_dict(s)
        for s in conn.execute("SELECT * FROM steps WHERE activity_id=? ORDER BY sort_order, due_date", (aid,)).fetchall()
    ]
    return ok(updated)


def _delete_activity(conn, args) -> list[types.TextContent]:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return ok({"error": f"Activity {aid} not found"})

    if args.get("permanent"):
        step_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM steps WHERE activity_id=?", (aid,)).fetchall()]
        cond_count = conn.execute(
            "SELECT COUNT(*) AS c FROM conditions WHERE activity_id=?", (aid,)).fetchone()["c"]
        log_ids = [aid] + step_ids
        log_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM activity_log WHERE item_id IN ({','.join('?' * len(log_ids))})",
            log_ids).fetchone()["c"]
        conn.execute("DELETE FROM conditions WHERE activity_id=?", (aid,))
        conn.execute("DELETE FROM steps WHERE activity_id=?", (aid,))
        conn.execute(
            f"DELETE FROM activity_log WHERE item_id IN ({','.join('?' * len(log_ids))})", log_ids)
        conn.execute("DELETE FROM activities WHERE id=?", (aid,))
        conn.commit()
        return ok({
            "deleted": aid,
            "name": current["name"],
            "mode": "permanent",
            "steps_deleted": len(step_ids),
            "conditions_deleted": cond_count,
            "log_entries_deleted": log_count,
        })

    batch = new_batch_id()
    try:
        events = transition(conn, "activity", aid, "skip", {"batch_id": batch})
    except ValueError as e:
        return ok({"error": str(e)})
    result = react(conn, events, batch)
    conn.commit()
    return ok({
        "deleted": aid,
        "name": current["name"],
        "mode": "soft",
        "batch_id": batch,
        "activity_status": "skipped",
        "steps_skipped": result["steps_skipped"],
    })


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

    # Which activities are relevant comes from the shared view layer: open
    # activities in the window, plus any parent of an actionable step in the
    # window regardless of its own status (a completed activity with a due
    # follow-up is still worth showing)
    open_acts = get_open_activities(conn, through_date=cutoff, include_undated=True)
    window_steps = get_actionable_items(conn, as_of_date=cutoff, include_undated=True)
    activity_ids = [a["activity_id"] for a in open_acts]
    for s in window_steps:
        if s["activity_id"] not in activity_ids:
            activity_ids.append(s["activity_id"])

    result = []
    for aid in activity_ids:
        # Hydrate the full row by primary key -- selection logic stays in the views
        a = conn.execute(
            "SELECT a.*, d.name as domain_name FROM activities a "
            "JOIN domains d ON a.domain_id = d.id WHERE a.id=?", (aid,)).fetchone()
        a = row_to_dict(a)
        step_ids = [s["step_id"] for s in window_steps if s["activity_id"] == aid]
        a["steps"] = [
            row_to_dict(conn.execute("SELECT * FROM steps WHERE id=?", (sid,)).fetchone())
            for sid in step_ids
        ]
        a["steps"].sort(key=lambda s: (s["due_date"] is not None, s["due_date"] or ""))
        overdue_steps = [s for s in a["steps"] if s.get("due_date") and s["due_date"] < today_str]
        a["has_overdue"] = len(overdue_steps) > 0
        result.append(a)

    result.sort(key=lambda a: (a["trigger_date"] is None, a["trigger_date"] or "",
                               a.get("sort_order") or 0))
    return ok({"today": today_str, "cutoff": cutoff, "items": result})


def _get_weather_current(conn, location) -> list[types.TextContent]:
    latest = conn.execute(
        "SELECT * FROM weather_log WHERE location=? ORDER BY recorded_at DESC LIMIT 1",
        (location,),
    ).fetchone()

    if not latest:
        return ok({"location": location, "error": "No weather data recorded for this location"})

    history = conn.execute(
        "SELECT recorded_at, temp_high, temp_low, conditions, precipitation FROM weather_log WHERE location=? ORDER BY recorded_at DESC LIMIT 7",
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
