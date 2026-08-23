"""Plan authoring: validation, insertion, sync, and ref resolution.

Extracted from server.py so the logic is shared and testable without MCP.
Functions return plain data (dicts/lists) and raise ValueError on failures;
the MCP server wraps results in ok()/err()."""

import json

from plansync.engine import (
    cascade_step_dates,
    compute_trigger_date,
    derive_conditions,
    log_change,
    new_batch_id,
    new_id,
    row_to_dict,
    slugify,
    step_due_date,
    transition,
    unique_ref_name,
)

VALID_METRICS = {"daily_high", "daily_low", "temp_high", "temp_low"}
ACTIVITY_SYNC_FIELDS = ("name", "description", "group_name")
STEP_SYNC_FIELDS = ("step_type", "lead_days", "description")


def canonical_tdef(tdef):
    if isinstance(tdef, str):
        tdef = json.loads(tdef)
    return json.dumps(tdef, sort_keys=True) if tdef is not None else None


def validate_domain_definition(defn):
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
        validate_activities(defn["activities"], errors)
    return errors


def validate_activities(activities, errors, existing_names=frozenset()):
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
            validate_dependency_refs(tdef, ref_names, f"activities[{i}].trigger_def", errors)
            validate_condition_metrics(tdef, f"activities[{i}].trigger_def", errors)

    return errors


def validate_condition_metrics(tdef, path, errors):
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
            validate_condition_metrics(sub, f"{path}.conditions[{j}]", errors)


def validate_dependency_refs(tdef, activity_names, path, errors):
    if not isinstance(tdef, dict):
        return
    if tdef.get("type") == "dependency" and "activity_ref" in tdef:
        if tdef["activity_ref"] not in activity_names:
            errors.append({"path": f"{path}.activity_ref", "error": f"References unknown activity: {tdef['activity_ref']}"})
    if tdef.get("type") == "compound":
        for j, sub in enumerate(tdef.get("conditions", [])):
            validate_dependency_refs(sub, activity_names, f"{path}.conditions[{j}]", errors)


def resolve_refs(tdef, name_to_id):
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
            resolved = resolve_refs(sub, name_to_id)
            if isinstance(resolved, dict) and resolved.get("_error"):
                return resolved
            resolved_subs.append(resolved)
        result["conditions"] = resolved_subs
    return result


def insert_activity(conn, domain_id, aid, act_def, name_to_id, default_sort):
    """Insert one activity with its steps and conditions. Raises ValueError on
    unresolvable dependency refs; caller owns the transaction."""
    trigger_def = act_def.get("trigger_def")
    if trigger_def is not None:
        trigger_def = resolve_refs(trigger_def, name_to_id)
        if isinstance(trigger_def, dict) and trigger_def.get("_error"):
            raise ValueError(trigger_def["_error"])

    trigger_def_str = json.dumps(trigger_def) if trigger_def is not None else None
    trigger_date = compute_trigger_date(trigger_def) if trigger_def is not None else None
    status = "watching" if trigger_def is not None else "active"
    ref_name = act_def.get("ref_name") or unique_ref_name(conn, domain_id, slugify(act_def["name"]))

    conn.execute(
        """INSERT INTO activities (id, domain_id, name, ref_name, description, group_name, status, trigger_type, trigger_def, trigger_date, sort_order)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            aid, domain_id, act_def["name"], ref_name, act_def.get("description"), act_def.get("group_name"),
            status, act_def.get("trigger_type"), trigger_def_str, trigger_date,
            act_def.get("sort_order", default_sort),
        ),
    )
    log_change(conn, "activity", aid, "created", None,
               {"name": act_def["name"], "ref_name": ref_name,
                "trigger_type": act_def.get("trigger_type"), "status": status})

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
        "ref_name": ref_name,
        "group_name": act_def.get("group_name"),
        "trigger_type": act_def.get("trigger_type"),
        "trigger_date": trigger_date,
        "status": status,
        "steps": created_steps,
    }


def sync_domain(conn, domain_row, defn, dry_run=False):
    """Diff a declaration against an existing domain and (unless dry_run)
    apply it. Returns a result dict (not wrapped in ok/err)."""
    did = domain_row["id"]
    db_acts = [row_to_dict(r) for r in conn.execute(
        "SELECT * FROM activities WHERE domain_id=?", (did,)).fetchall()]
    by_ref = {a["ref_name"]: a for a in db_acts}
    by_name = {a["name"]: a for a in db_acts}

    matched, to_create = [], []
    for decl in defn["activities"]:
        ref = decl.get("ref_name")
        db_act = by_ref.get(ref) if ref else (by_name.get(decl["name"]) or by_ref.get(slugify(decl["name"])))
        (matched if db_act is not None else to_create).append((db_act, decl))
    to_create = [decl for _, decl in to_create]

    matched_ids = {a["id"] for a, _ in matched}
    flagged = [{"id": a["id"], "name": a["name"], "ref_name": a["ref_name"], "status": a["status"]}
               for a in db_acts if a["id"] not in matched_ids]

    name_to_id = {a["name"]: a["id"] for a in db_acts}
    for decl in to_create:
        name_to_id[decl["name"]] = new_id()

    updates, step_creates, step_updates, step_flags = [], [], [], []
    for db_act, decl in matched:
        changes = {}
        for f in ACTIVITY_SYNC_FIELDS:
            if f in decl and decl[f] != db_act.get(f):
                changes[f] = {"old": db_act.get(f), "new": decl[f]}
        decl_tdef = decl.get("trigger_def")
        if decl_tdef is not None:
            decl_tdef = resolve_refs(decl_tdef, name_to_id)
            if isinstance(decl_tdef, dict) and decl_tdef.get("_error"):
                raise ValueError(decl_tdef["_error"])
        if "trigger_def" in decl and canonical_tdef(decl_tdef) != canonical_tdef(db_act.get("trigger_def")):
            changes["trigger_def"] = {"old": db_act.get("trigger_def"), "new": decl_tdef}
            if decl.get("trigger_type") != db_act.get("trigger_type"):
                changes["trigger_type"] = {"old": db_act.get("trigger_type"), "new": decl.get("trigger_type")}
        if changes:
            updates.append({"id": db_act["id"], "ref_name": db_act["ref_name"], "changes": changes})

        db_steps = {s["name"]: row_to_dict(s) for s in conn.execute(
            "SELECT * FROM steps WHERE activity_id=?", (db_act["id"],)).fetchall()}
        decl_steps = decl.get("steps", [])
        for sd in decl_steps:
            db_step = db_steps.get(sd["name"])
            if db_step is None:
                step_creates.append({"activity_id": db_act["id"], "activity_ref": db_act["ref_name"],
                                     "name": sd["name"], "decl": sd})
                continue
            s_changes = {f: {"old": db_step.get(f), "new": sd[f]}
                         for f in STEP_SYNC_FIELDS if f in sd and sd[f] != db_step.get(f)}
            if s_changes:
                step_updates.append({"id": db_step["id"], "activity_id": db_act["id"],
                                     "name": sd["name"], "changes": s_changes})
        decl_step_names = {sd["name"] for sd in decl_steps}
        for s_name, db_step in db_steps.items():
            if s_name not in decl_step_names:
                step_flags.append({"id": db_step["id"], "name": s_name,
                                   "activity_ref": db_act["ref_name"], "status": db_step["status"]})

    result = {
        "mode": "sync",
        "domain_id": did,
        "dry_run": dry_run,
        "applied": False,
        "created": [{"name": d["name"]} for d in to_create],
        "updated": updates,
        "flagged_missing": flagged,
        "steps_created": [{"activity_ref": sc["activity_ref"], "name": sc["name"]} for sc in step_creates],
        "steps_updated": [{"name": su["name"], "changes": su["changes"]} for su in step_updates],
        "steps_flagged": step_flags,
    }
    if dry_run:
        return result

    batch = new_batch_id()
    created_results = []
    max_sort = max((a.get("sort_order") or 0 for a in db_acts), default=0)
    for i, decl in enumerate(to_create):
        created_results.append(insert_activity(conn, did, name_to_id[decl["name"]], decl,
                                               name_to_id, default_sort=max_sort + i + 1))

    for upd in updates:
        aid = upd["id"]
        db_act = next(a for a in db_acts if a["id"] == aid)
        changes = upd["changes"]
        sets, vals = [], []
        for f, ch in changes.items():
            if f == "trigger_def":
                vals.append(json.dumps(ch["new"]))
            else:
                vals.append(ch["new"])
            sets.append(f"{f}=?")
        sets.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(aid)
        conn.execute(f"UPDATE activities SET {', '.join(sets)} WHERE id=?", vals)
        log_change(conn, "activity", aid, "manual_update",
                   {f: ch["old"] for f, ch in changes.items()},
                   {f: ch["new"] for f, ch in changes.items()},
                   batch_id=batch)
        if "trigger_def" in changes:
            new_tdef = changes["trigger_def"]["new"]
            conn.execute("DELETE FROM conditions WHERE activity_id=?", (aid,))
            for cond_def in derive_conditions(new_tdef):
                conn.execute(
                    "INSERT INTO conditions (id, activity_id, condition_type, definition) VALUES (?,?,?,?)",
                    (new_id(), aid, cond_def["condition_type"], json.dumps(cond_def["definition"])),
                )
            new_td = compute_trigger_date(new_tdef)
            if new_td != db_act.get("trigger_date"):
                conn.execute("UPDATE activities SET trigger_date=? WHERE id=?", (new_td, aid))
                cascade_step_dates(conn, aid, new_td, batch_id=batch)
            if db_act.get("trigger_def") is None and db_act.get("status") == "active":
                transition(conn, "activity", aid, "watch", {"batch_id": batch})

    for sc in step_creates:
        parent = conn.execute("SELECT trigger_date FROM activities WHERE id=?",
                              (sc["activity_id"],)).fetchone()
        sd = sc["decl"]
        due = step_due_date(parent["trigger_date"], sd["step_type"], sd["lead_days"])
        max_step_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM steps WHERE activity_id=?",
            (sc["activity_id"],)).fetchone()["m"]
        sid = new_id()
        conn.execute(
            """INSERT INTO steps (id, activity_id, name, description, step_type, lead_days, due_date, sort_order)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, sc["activity_id"], sd["name"], sd.get("description"),
             sd["step_type"], sd["lead_days"], due, max_step_sort + 1),
        )
        log_change(conn, "step", sid, "created", None,
                   {"name": sd["name"], "activity_id": sc["activity_id"], "due_date": due},
                   batch_id=batch)

    for su in step_updates:
        changes = su["changes"]
        sets = [f"{f}=?" for f in changes]
        vals = [ch["new"] for ch in changes.values()]
        if "lead_days" in changes or "step_type" in changes:
            parent = conn.execute(
                "SELECT trigger_date FROM activities WHERE id=?", (su["activity_id"],)).fetchone()
            if parent["trigger_date"]:
                current_step = conn.execute("SELECT * FROM steps WHERE id=?", (su["id"],)).fetchone()
                new_type = changes.get("step_type", {}).get("new", current_step["step_type"])
                new_lead = changes.get("lead_days", {}).get("new", current_step["lead_days"])
                sets.append("due_date=?")
                vals.append(step_due_date(parent["trigger_date"], new_type, new_lead))
        sets.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(su["id"])
        conn.execute(f"UPDATE steps SET {', '.join(sets)} WHERE id=?", vals)
        log_change(conn, "step", su["id"], "manual_update",
                   {f: ch["old"] for f, ch in changes.items()},
                   {f: ch["new"] for f, ch in changes.items()},
                   batch_id=batch)

    conn.commit()
    result["applied"] = True
    result["batch_id"] = batch
    result["created"] = created_results
    return result
