"""dispatch.instantiate — path template instantiation.

Reads a path YAML template, fills parameters from domain context,
and inserts items into the dispatch store.
"""

import json
import os
import re
import string

import yaml

from dispatch.store import connect, insert_item, derive_conditions, log_event, new_id


PATHS_DIR = os.environ.get(
    "DISPATCH_PATHS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "paths"),
)


def list_paths():
    paths = []
    if not os.path.isdir(PATHS_DIR):
        return paths
    for entry in sorted(os.listdir(PATHS_DIR)):
        path_file = os.path.join(PATHS_DIR, entry, "path.yaml")
        if os.path.isfile(path_file):
            with open(path_file) as f:
                data = yaml.safe_load(f)
            paths.append({
                "id": data.get("id", entry),
                "version": data.get("version", "0.0.0"),
                "name": data.get("name", entry),
                "description": data.get("description", ""),
                "params": data.get("params", []),
            })
    return paths


def load_path(path_id):
    # Try direct directory match
    path_file = os.path.join(PATHS_DIR, path_id, "path.yaml")
    if not os.path.isfile(path_file):
        # Try matching by id field in path.yaml files
        for entry in os.listdir(PATHS_DIR):
            candidate = os.path.join(PATHS_DIR, entry, "path.yaml")
            if os.path.isfile(candidate):
                with open(candidate) as f:
                    data = yaml.safe_load(f)
                if data.get("id") == path_id:
                    path_file = candidate
                    break
        else:
            raise FileNotFoundError(f"Path not found: {path_id}")

    with open(path_file) as f:
        return yaml.safe_load(f)


def validate_params(path_def, provided_params):
    errors = []
    for param_spec in path_def.get("params", []):
        name = param_spec["name"]
        required = param_spec.get("required", True)
        if required and name not in provided_params:
            errors.append(f"Missing required parameter: {name}")
    return errors


def instantiate(path_id, domain, params, conn=None):
    path_def = load_path(path_id)

    errors = validate_params(path_def, params)
    if errors:
        raise ValueError("Parameter errors: " + "; ".join(errors))

    version = path_def.get("version", "0.0.0")
    full_path_id = f"{path_def.get('id', path_id)}@{version}"

    item_templates = path_def.get("items", [])
    ref_to_id = {}
    created_ids = []

    def _do_insert(c):
        nonlocal ref_to_id, created_ids
        batch_id = new_id()

        for tmpl in item_templates:
            per_entity = tmpl.get("per_entity")
            if per_entity and per_entity in params:
                entities = params[per_entity]
                if isinstance(entities, list):
                    for entity in entities:
                        entity_ctx = entity if isinstance(entity, dict) else {"name": entity}
                        _insert_one(c, tmpl, domain, params, entity_ctx,
                                    full_path_id, ref_to_id, created_ids, batch_id)
                else:
                    _insert_one(c, tmpl, domain, params, None,
                                full_path_id, ref_to_id, created_ids, batch_id)
            else:
                _insert_one(c, tmpl, domain, params, None,
                            full_path_id, ref_to_id, created_ids, batch_id)

        log_event(
            c, "items_instantiated", batch_id=batch_id,
            domain=domain,
            payload={"path_id": full_path_id, "params": params,
                     "item_count": len(created_ids)},
        )
        c.commit()
        return created_ids

    if conn:
        return _do_insert(conn)
    else:
        with connect() as c:
            return _do_insert(c)


def _insert_one(conn, tmpl, domain, params, entity_ctx,
                full_path_id, ref_to_id, created_ids, batch_id):
    ctx = {**params}
    if entity_ctx:
        ctx["entity"] = entity_ctx
        # Flatten entity properties for {entity.name}, {entity.sun} etc.
        for k, v in entity_ctx.items():
            ctx[f"entity.{k}"] = v
            if isinstance(v, dict):
                for sk, sv in v.items():
                    ctx[f"entity.{k}.{sk}"] = sv

    name = _substitute(tmpl["name"], ctx)
    desc = _substitute(tmpl.get("description", ""), ctx)
    group = _substitute(tmpl.get("group", ""), ctx)
    ref = tmpl.get("ref", "")
    source_ref = f"{ref}:{entity_ctx.get('name', '')}" if entity_ctx and ref else ref

    trigger_def = _resolve_trigger_refs(tmpl["trigger"], ref_to_id)

    checklist = tmpl.get("checklist", [])

    item_id = insert_item(
        conn, domain, name, trigger_def,
        description=desc,
        source_ref=source_ref,
        path_id=full_path_id,
        group=group,
        checklist=checklist,
        sort_order=tmpl.get("sort_order", 0),
    )
    derive_conditions(conn, item_id, trigger_def)

    if ref:
        key = f"{ref}:{entity_ctx.get('name', '')}" if entity_ctx else ref
        ref_to_id[key] = item_id
        ref_to_id[ref] = item_id

    created_ids.append(item_id)

    log_event(
        conn, "item_created", batch_id=batch_id,
        domain=domain, item_id=item_id, source_ref=source_ref,
        payload={"name": name, "path_id": full_path_id},
    )


def _substitute(template, ctx):
    if not template:
        return template
    # Replace {entity.name} style refs with flat keys {entity__name} first,
    # then use format_map.  This avoids Python's attribute lookup on dicts.
    import re
    def _dot_to_key(m):
        key = m.group(1)
        return ctx.get(key, m.group(0))
    result = re.sub(r'\{([\w.]+)\}', _dot_to_key, template)
    try:
        return result.format_map(_SafeDict(ctx))
    except (KeyError, IndexError):
        return result


class _SafeDict(dict):
    def __missing__(self, key):
        return f"{{{key}}}"


def _resolve_trigger_refs(trigger_def, ref_to_id):
    """Replace ref-name references in after triggers with real item IDs."""
    if not isinstance(trigger_def, dict):
        return trigger_def

    ttype = trigger_def.get("type")
    if ttype == "after":
        ref = trigger_def.get("item_ref", "")
        if ref in ref_to_id:
            return {**trigger_def, "item_ref": ref_to_id[ref]}
        return trigger_def

    if ttype == "compound":
        return {
            **trigger_def,
            "triggers": [_resolve_trigger_refs(t, ref_to_id)
                         for t in trigger_def.get("triggers", [])],
        }

    return trigger_def
