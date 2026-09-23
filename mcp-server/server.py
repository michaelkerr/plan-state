#!/usr/bin/env python3
"""Plan-Sync MCP server with SSE transport and HTTP API.

Exposes the SQLite plan store as typed tools for Hermes (via MCP over SSE)
and as HTTP endpoints for cron scripts (sync, briefing, nudge).
"""

import asyncio
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import date, timedelta

from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from plansync.engine import (
    cascade_step_dates,
    compute_trigger_date,
    connect,
    db_path,
    defer_trigger_def,
    derive_conditions,
    get_actionable_items,
    get_db,
    get_open_activities,
    log_change,
    new_batch_id,
    new_id,
    react,
    row_to_dict,
    step_due_date,
    transition,
)
from plansync.authoring import (
    insert_activity,
    sync_domain,
    validate_activities,
    validate_domain_definition,
)

log = logging.getLogger("plansync")

server = Server("plansync")
sse = SseServerTransport("/messages/")


def require(args: dict, *fields: str) -> None:
    missing = [f for f in fields if f not in args or args[f] is None]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")


def ok(data) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(data, default=str, indent=2))],
    )


def err(message, details=None) -> types.CallToolResult:
    body = {"error": message}
    if details is not None:
        body["details"] = details
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(body, default=str, indent=2))],
        isError=True,
    )


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
            description="Update fields on an existing activity. Re-cascades step dates if trigger_date changes. Status changes must go through complete_activity, defer_activity, or delete_activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "group_name": {"type": "string", "description": "Optional bundle label within the domain (crop, bed, species). Display only."},
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
            name="undo",
            description="Revert the most recent batched operation (completion cascade, deferral, soft delete, trigger fire, step status change) -- or, with item_type/item_id, the most recent batch touching that item. Restores statuses and logged field values. Undoing an undo is not supported.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_type": {"type": "string", "enum": ["activity", "step"]},
                    "item_id": {"type": "string"},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="add_step",
            description="Add a step to an existing activity. Due date derives from the parent's trigger_date (prep = before, follow_up = after); NULL when the parent has no trigger_date (set it later via update_step or by adding a trigger to the parent).",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "name": {"type": "string"},
                    "step_type": {"type": "string", "enum": ["prep", "follow_up"]},
                    "lead_days": {"type": "integer", "minimum": 0},
                    "description": {"type": "string"},
                },
                "required": ["activity_id", "name", "step_type", "lead_days"],
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
            description="Bulk-load a complete domain definition (domain + all activities, steps, conditions) in one atomic operation. Validates the definition, resolves activity_ref dependencies by name, and rolls back on any error. If the domain already exists, switches to sync mode: diffs the declaration against DB state (matched by ref_name, then name) -- new activities are created, changed ones updated, DB rows missing from the declaration are flagged but never deleted. dry_run=true returns the diff without applying.",
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Complete domain definition conforming to domain_schema.json",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "default": False,
                        "description": "Sync mode only: report the diff without applying it",
                    },
                },
                "required": ["definition"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    log.info("tool_call: %s", name)
    try:
        with connect() as conn:
            if name == "get_domains":
                return _get_domains(conn)
            elif name == "get_domain_plan":
                require(arguments, "domain_id")
                return _get_domain_plan(conn, arguments["domain_id"])
            elif name == "update_activity":
                require(arguments, "activity_id")
                return _update_activity(conn, arguments)
            elif name == "update_step":
                require(arguments, "step_id")
                return _update_step(conn, arguments)
            elif name == "complete_activity":
                require(arguments, "activity_id")
                return _complete_activity(conn, arguments)
            elif name == "defer_activity":
                require(arguments, "activity_id", "new_date")
                return _defer_activity(conn, arguments)
            elif name == "add_observation":
                require(arguments, "domain_id", "observation_text")
                return _add_observation(conn, arguments)
            elif name == "get_upcoming":
                return _get_upcoming(conn, arguments.get("days_ahead", 14))
            elif name == "get_weather_current":
                require(arguments, "location")
                return _get_weather_current(conn, arguments["location"])
            elif name == "load_domain":
                require(arguments, "definition")
                return _load_domain(conn, arguments)
            elif name == "add_activities":
                require(arguments, "domain_id", "activities")
                return _add_activities(conn, arguments)
            elif name == "delete_activity":
                require(arguments, "activity_id")
                return _delete_activity(conn, arguments)
            elif name == "add_step":
                require(arguments, "activity_id", "name", "step_type", "lead_days")
                return _add_step(conn, arguments)
            elif name == "undo":
                return _undo(conn, arguments)
            else:
                return err(f"Unknown tool: {name}")
    except ValueError as e:
        log.warning("tool_call %s validation error: %s", name, e)
        return err(str(e))
    except (KeyError, TypeError) as e:
        log.warning("tool_call %s input error: %s", name, e)
        return err(f"Invalid input: {e}")
    except json.JSONDecodeError as e:
        log.warning("tool_call %s JSON error: %s", name, e)
        return err(f"JSON decode error: {e}")
    except sqlite3.Error as e:
        log.error("tool_call %s database error: %s", name, e)
        return err(f"Database error: {e}")
    except Exception as e:
        log.exception("tool_call %s unexpected error", name)
        return err(f"Internal error: {type(e).__name__}: {e}")


# ── Tool implementations (unchanged from stdio version) ──────────


def _get_domains(conn) -> types.CallToolResult:
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


def _get_domain_plan(conn, domain_id) -> types.CallToolResult:
    domain = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
    if not domain:
        return err(f"Domain {domain_id} not found")
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


def _load_domain(conn, args) -> types.CallToolResult:
    defn = args.get("definition")
    if not defn:
        return err("Missing 'definition' field")

    errors = validate_domain_definition(defn)
    if errors:
        return err("Validation failed", details=errors)

    name = defn["name"]
    existing = conn.execute("SELECT * FROM domains WHERE name=?", (name,)).fetchone()
    if existing:
        try:
            result = sync_domain(conn, existing, defn, dry_run=bool(args.get("dry_run")))
            return ok(result)
        except (ValueError, sqlite3.Error) as e:
            conn.rollback()
            return err(str(e))

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
            activity_results.append(insert_activity(conn, did, aid, act_def, name_to_id, default_sort=i))

        conn.commit()
        return ok({
            "id": did,
            "name": name,
            "location": defn.get("location"),
            "activities": activity_results,
        })

    except (ValueError, sqlite3.Error) as e:
        conn.rollback()
        return err(str(e))


def _add_activities(conn, args) -> types.CallToolResult:
    domain_id = args.get("domain_id")
    activities = args.get("activities")

    domain = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
    if not domain:
        return err(f"Domain {domain_id} not found")
    if not isinstance(activities, list) or len(activities) == 0:
        return err("activities must be a non-empty array")

    existing = conn.execute(
        "SELECT id, name, sort_order FROM activities WHERE domain_id=?", (domain_id,)
    ).fetchall()
    existing_names = {r["name"] for r in existing}

    errors = validate_activities(activities, [], existing_names)
    if errors:
        return err("Validation failed", details=errors)

    name_to_id = {r["name"]: r["id"] for r in existing}
    for act_def in activities:
        name_to_id[act_def["name"]] = new_id()
    max_sort = max((r["sort_order"] or 0 for r in existing), default=0)

    try:
        results = []
        for i, act_def in enumerate(activities):
            aid = name_to_id[act_def["name"]]
            results.append(insert_activity(conn, domain_id, aid, act_def, name_to_id, default_sort=max_sort + i + 1))
        conn.commit()
        return ok({
            "domain_id": domain_id,
            "domain_name": domain["name"],
            "activities": results,
        })
    except (ValueError, sqlite3.Error) as e:
        conn.rollback()
        return err(str(e))


def _update_activity(conn, args) -> types.CallToolResult:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return err(f"Activity {aid} not found")
    current = row_to_dict(current)

    if "ref_name" in args:
        return err("ref_name is immutable: it is the stable identity used to match "
                   "declared activities to DB rows across renames. Rename via 'name'.")

    if "status" in args:
        return err("status cannot be set through update_activity: use complete_activity, "
                   "defer_activity, or delete_activity (skip) instead")

    updatable = ["name", "description", "group_name", "trigger_type", "trigger_def", "trigger_date"]
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
        return err("No fields to update")

    sets.append("updated_at=CURRENT_TIMESTAMP")
    vals.append(aid)
    conn.execute(f"UPDATE activities SET {', '.join(sets)} WHERE id=?", vals)

    if "trigger_def" in changes:
        conn.execute("DELETE FROM conditions WHERE activity_id=?", (aid,))
        for cond_def in derive_conditions(args["trigger_def"]):
            conn.execute(
                "INSERT INTO conditions (id, activity_id, condition_type, definition) VALUES (?,?,?,?)",
                (new_id(), aid, cond_def["condition_type"], json.dumps(cond_def["definition"])),
            )
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

    log_change(conn, "activity", aid, "manual_update", {k: v["old"] for k, v in changes.items()}, {k: v["new"] for k, v in changes.items()})

    conn.commit()

    updated = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    updated = row_to_dict(updated)
    updated["steps"] = [
        row_to_dict(s)
        for s in conn.execute("SELECT * FROM steps WHERE activity_id=? ORDER BY sort_order, due_date", (aid,)).fetchall()
    ]
    return ok(updated)


def _add_step(conn, args) -> types.CallToolResult:
    aid = args["activity_id"]
    activity = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not activity:
        return err(f"Activity {aid} not found")
    if args.get("step_type") not in ("prep", "follow_up"):
        return err(f"Invalid step_type: {args.get('step_type')!r} (expected 'prep' or 'follow_up')")
    lead_days = args.get("lead_days")
    if not isinstance(lead_days, int) or lead_days < 0:
        return err("lead_days must be a non-negative integer")

    sid = new_id()
    due = step_due_date(activity["trigger_date"], args["step_type"], lead_days)
    max_sort = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS m FROM steps WHERE activity_id=?", (aid,)
    ).fetchone()["m"]
    conn.execute(
        """INSERT INTO steps (id, activity_id, name, description, step_type, lead_days, due_date, sort_order)
           VALUES (?,?,?,?,?,?,?,?)""",
        (sid, aid, args["name"], args.get("description"),
         args["step_type"], lead_days, due, max_sort + 1),
    )
    log_change(conn, "step", sid, "created", None,
               {"name": args["name"], "step_type": args["step_type"],
                "lead_days": lead_days, "due_date": due, "activity_id": aid})
    conn.commit()

    step = row_to_dict(conn.execute("SELECT * FROM steps WHERE id=?", (sid,)).fetchone())
    step["activity_name"] = activity["name"]
    return ok(step)


def _step_status_event(current, desired):
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


def _update_step(conn, args) -> types.CallToolResult:
    sid = args["step_id"]
    current = conn.execute("SELECT * FROM steps WHERE id=?", (sid,)).fetchone()
    if not current:
        return err(f"Step {sid} not found")
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
        return err("No fields to update")

    batch = new_batch_id()

    if sets:
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
            return err(f"cannot move step {sid} from '{current['status']}' "
                       f"to '{desired_status}': no such transition")
        context["batch_id"] = batch
        try:
            transition(conn, "step", sid, event, context)
        except ValueError as e:
            return err(str(e))

    conn.commit()

    updated = conn.execute("SELECT * FROM steps WHERE id=?", (sid,)).fetchone()
    updated = row_to_dict(updated)
    activity = conn.execute(
        "SELECT id, name, group_name FROM activities WHERE id=?",
        (updated["activity_id"],),
    ).fetchone()
    if activity:
        updated["activity_name"] = activity["name"]
        updated["activity_group"] = activity["group_name"]
    return ok(updated)


def _complete_activity(conn, args) -> types.CallToolResult:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return err(f"Activity {aid} not found")

    batch = new_batch_id()
    context = {"batch_id": batch}
    if args.get("notes"):
        context["extra"] = {"notes": args["notes"]}
    try:
        events = transition(conn, "activity", aid, "complete", context)
    except ValueError as e:
        return err(str(e))

    result = react(conn, events, batch)
    conn.commit()
    return ok({
        "completed": aid,
        "batch_id": batch,
        "prep_steps_completed": result["steps_completed"],
        "follow_up_steps_due": result["follow_ups_promoted"],
        "dependent_activities_activated": result["dependencies_fired"],
    })


def _defer_activity(conn, args) -> types.CallToolResult:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return err(f"Activity {aid} not found")

    new_date = args.get("new_date")
    reason = args.get("reason", "")
    if not new_date:
        return err("new_date is required: deferral moves the trigger date (there is no 'deferred' status)")

    batch = new_batch_id()
    try:
        transition(conn, "activity", aid, "defer", {"batch_id": batch})
    except ValueError as e:
        return err(str(e))

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


def _delete_activity(conn, args) -> types.CallToolResult:
    aid = args["activity_id"]
    current = conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    if not current:
        return err(f"Activity {aid} not found")

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
        return err(str(e))
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


UNDO_RESTORABLE_FIELDS = {
    "activity": {"name", "description", "group_name", "trigger_date", "trigger_def", "trigger_type"},
    "step": {"name", "description", "lead_days", "step_type", "due_date"},
}


def _restore_fields(conn, item_type, item_id, old_value):
    table = "activities" if item_type == "activity" else "steps"
    allowed = UNDO_RESTORABLE_FIELDS[item_type]
    sets, vals = [], []
    for k, v in old_value.items():
        if k == "status" or k not in allowed:
            continue
        if k == "trigger_def" and isinstance(v, (dict, list)):
            v = json.dumps(v)
        sets.append(f"{k}=?")
        vals.append(v)
    if sets:
        sets.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(item_id)
        conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)
    return [k for k in old_value if k != "status" and k in allowed]


def _undo(conn, args) -> types.CallToolResult:
    item_type, item_id = args.get("item_type"), args.get("item_id")
    q = ("SELECT batch_id FROM activity_log l WHERE batch_id IS NOT NULL "
         "AND NOT EXISTS (SELECT 1 FROM activity_log u "
         "WHERE u.batch_id = l.batch_id AND u.action='undo')")
    params = []
    if item_type:
        q += " AND item_type=?"
        params.append(item_type)
    if item_id:
        q += " AND item_id=?"
        params.append(item_id)
    q += " ORDER BY id DESC LIMIT 1"
    row = conn.execute(q, params).fetchone()
    if not row:
        return err("Nothing to undo (no batched operations found)")
    batch = row["batch_id"]

    if conn.execute(
        "SELECT 1 FROM activity_log WHERE action='undo' AND json_extract(new_value, '$.undo_of')=?",
        (batch,),
    ).fetchone():
        return err(f"Batch {batch} was already undone; undoing an undo is not supported")

    entries = [row_to_dict(e) for e in conn.execute(
        "SELECT * FROM activity_log WHERE batch_id=? ORDER BY id DESC", (batch,)).fetchall()]

    undo_batch = new_batch_id()
    reverted, skipped = [], []
    try:
        for e in entries:
            old = e["old_value"] or {}
            if e["item_type"] not in ("activity", "step"):
                skipped.append({"item_id": e["item_id"], "action": e["action"],
                                "reason": f"cannot revert {e['item_type']} entries"})
                continue
            if e["action"] in ("status_change", "trigger_fire"):
                transition(conn, e["item_type"], e["item_id"], "revert",
                           {"to_status": old.get("status"), "batch_id": undo_batch})
                restored = _restore_fields(conn, e["item_type"], e["item_id"], old)
                if e["action"] == "trigger_fire":
                    conn.execute("UPDATE activities SET trigger_fired=NULL WHERE id=?", (e["item_id"],))
                reverted.append({"item_type": e["item_type"], "item_id": e["item_id"],
                                 "status": old.get("status"), "fields": restored})
            elif e["action"] in ("date_cascade", "manual_update"):
                restored = _restore_fields(conn, e["item_type"], e["item_id"], old)
                reverted.append({"item_type": e["item_type"], "item_id": e["item_id"],
                                 "fields": restored})
            else:
                skipped.append({"item_id": e["item_id"], "action": e["action"],
                                "reason": f"'{e['action']}' entries are not reverted"})
    except ValueError as exc:
        conn.rollback()
        return err(f"Undo failed, nothing changed: {exc}")

    root = entries[-1]
    log_change(conn, root["item_type"], root["item_id"], "undo", None,
               {"undo_of": batch, "reverted": len(reverted), "skipped": len(skipped)},
               batch_id=undo_batch)
    conn.commit()
    return ok({
        "undo_of": batch,
        "undo_batch_id": undo_batch,
        "reverted": reverted,
        "skipped": skipped,
    })


def _add_observation(conn, args) -> types.CallToolResult:
    domain_id = args["domain_id"]
    log_change(
        conn, "domain", domain_id, "observation",
        None,
        {
            "domain_id": domain_id,
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
        "recorded": True,
        "affected_activities": affected,
    })


def _get_upcoming(conn, days_ahead) -> types.CallToolResult:
    cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
    today_str = date.today().isoformat()

    open_acts = get_open_activities(conn, through_date=cutoff, include_undated=True)
    window_steps = get_actionable_items(conn, as_of_date=cutoff, include_undated=True)
    activity_ids = [a["activity_id"] for a in open_acts]
    for s in window_steps:
        if s["activity_id"] not in activity_ids:
            activity_ids.append(s["activity_id"])

    result = []
    for aid in activity_ids:
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


def _get_weather_current(conn, location) -> types.CallToolResult:
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


# ── HTTP API endpoints (for Hermes cron scripts) ─────────────


async def api_health(request: Request):
    try:
        with connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return JSONResponse({"status": "ok", "db": db_path()})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=503)


async def api_sync(request: Request):
    log.info("api_sync called")
    try:
        text = await asyncio.to_thread(_run_sync)
        return PlainTextResponse(text)
    except Exception as e:
        log.exception("api_sync failed")
        return PlainTextResponse(f"sync error: {e}\n", status_code=500)


def _proxy_dispatch(path):
    """Fetch briefing or nudge text from the dispatch container.

    During the parallel run, sessions and old cron names still call this
    host. Serving dispatch here keeps that curl on the new database.
    """
    base = os.environ.get("DISPATCH_UPSTREAM", "http://plansync-new:8082").rstrip("/")
    with urllib.request.urlopen(base + path, timeout=20) as resp:
        return resp.read().decode()


async def api_briefing(request: Request):
    log.info("api_briefing called")
    try:
        text = await asyncio.to_thread(_proxy_dispatch, "/api/briefing")
        return PlainTextResponse(text if text.strip() else "No briefing data available.\n")
    except Exception as e:
        log.exception("api_briefing failed")
        return PlainTextResponse(f"briefing error: {e}\n", status_code=500)


async def api_nudge(request: Request):
    log.info("api_nudge called")
    try:
        text = await asyncio.to_thread(_proxy_dispatch, "/api/nudge")
        return PlainTextResponse(text)
    except Exception as e:
        log.exception("api_nudge failed")
        return PlainTextResponse(f"nudge error: {e}\n", status_code=500)


# ── Internal sync scheduler ──────────────────────────────────


def _run_sync():
    """Run the sync pipeline without sys.exit(). Returns summary text."""
    from sync.sync_pipeline import (
        SyncSummary, pull_weather, evaluate_conditions,
        evaluate_triggers, cascade_dates, check_overdue, save_output,
        _today, _now,
    )
    today = _today()
    now = _now()
    summary = SyncSummary(today=today)
    with connect() as conn:
        try:
            pull_weather(conn, summary, today=today, now=now)
            conn.commit()
            evaluate_conditions(conn, summary, today=today, now=now)
            conn.commit()
            evaluate_triggers(conn, summary, today=today, now=now)
            conn.commit()
            cascade_dates(conn, summary, now=now)
            conn.commit()
            check_overdue(conn, summary, today=today)
            conn.commit()
            save_output(summary, today=today, now=now)
        except Exception as e:
            summary.errors.append(f"Fatal: {e}")
            conn.rollback()
    return summary.to_stdout() or "sync complete, no changes\n"


async def _sync_loop():
    interval = int(os.environ.get("SYNC_INTERVAL", "3600"))
    log.info("internal sync scheduler started (interval=%ds)", interval)
    while True:
        await asyncio.sleep(interval)
        log.info("running scheduled sync")
        try:
            result = await asyncio.to_thread(_run_sync)
            log.info("scheduled sync completed: %s", result.strip())
        except Exception:
            log.exception("scheduled sync failed")


# ── App assembly ─────────────────────────────────────────────


class _SSEHandler:
    async def __call__(self, scope, receive, send):
        async with sse.connect_sse(scope, receive, send) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )


_sse_handler = _SSEHandler()


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_sync_loop())
    yield
    task.cancel()


app = Starlette(
    routes=[
        Route("/health", api_health),
        Route("/api/sync", api_sync, methods=["GET", "POST"]),
        Route("/api/briefing", api_briefing),
        Route("/api/nudge", api_nudge),
        Route("/sse", _sse_handler),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if "--stdio" in sys.argv:
        from mcp.server.stdio import stdio_server

        async def _run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream, write_stream,
                    server.create_initialization_options(),
                )

        log.info("starting plansync MCP server (stdio)")
        asyncio.run(_run_stdio())
    else:
        import uvicorn

        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "8082"))
        log.info("starting plansync MCP server on %s:%d", host, port)
        uvicorn.run(app, host=host, port=port, log_level="info")
