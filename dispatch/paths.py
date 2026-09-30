"""dispatch.paths — path templates: loading, validation, preview, saving.

Pure template logic, no DB writes.  instantiate.py expands a template
with this module and inserts the result; the draft_path tool and
`dispatch check-path` use it to validate and preview a template before
anyone relies on it.

Built-in templates ship in the image (DISPATCH_PATHS_DIR).  Templates
authored by users are saved next to the DB (DISPATCH_USER_PATHS_DIR,
default <db dir>/paths) so they survive rebuilds and are not repo code.
"""

import copy
import os
import re
from datetime import datetime, timedelta

import yaml

from dispatch.store import db_path


PARAM_TYPES = ("string", "number", "date", "list", "entity_ref")
TRIGGER_TYPES = ("calendar", "condition", "after", "compound")
METRICS = ("daily_high", "daily_low", "temp_high", "temp_low")
OPERATORS = (">=", "<=", ">", "<", "==")

ITEM_KEYS = {"ref", "name", "description", "group", "trigger", "checklist",
             "sort_order", "per_entity"}
TRIGGER_KEYS = {
    "calendar": {"type", "date", "prep_days"},
    "condition": {"type", "rules", "earliest_date"},
    "after": {"type", "item_ref", "event", "offset_days"},
    "compound": {"type", "op", "triggers"},
}
RULE_KEYS = {"metric", "operator", "value", "sustained_days"}
REJECTED_KEYS = {
    "recurrence": "Recurrence is not supported. Re-instantiate the path each season.",
    "recurring": "Recurrence is not supported. Re-instantiate the path each season.",
    "steps": "Steps do not exist in dispatch. Use a checklist, or a separate item with an after-trigger.",
    "conditions": "Conditions are derived from the trigger. Put rules in a condition trigger instead.",
}

METRIC_LABELS = {
    "daily_high": "daily high",
    "daily_low": "daily low",
    "temp_high": "daily high",
    "temp_low": "daily low",
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PARAM_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PLACEHOLDER_RE = re.compile(r"\{([\w.]+)\}")
WHOLE_PLACEHOLDER_RE = re.compile(r"^\{(\w+)\}$")


# --- Locations ---

def builtin_paths_dir():
    return os.environ.get(
        "DISPATCH_PATHS_DIR",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "paths"),
    )


def user_paths_dir():
    return os.environ.get(
        "DISPATCH_USER_PATHS_DIR",
        os.path.join(os.path.dirname(db_path()), "paths"),
    )


def _path_files():
    """Yield (source, file) for every path.yaml, built-ins first."""
    for source, root in (("built-in", builtin_paths_dir()),
                         ("custom", user_paths_dir())):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            path_file = os.path.join(root, entry, "path.yaml")
            if os.path.isfile(path_file):
                yield source, path_file


# --- Loading ---

def list_paths():
    paths = []
    for source, path_file in _path_files():
        with open(path_file) as f:
            data = yaml.safe_load(f) or {}
        entry = os.path.basename(os.path.dirname(path_file))
        paths.append({
            "id": data.get("id", entry),
            "version": data.get("version", "0.0.0"),
            "name": data.get("name", entry),
            "description": data.get("description", ""),
            "params": data.get("params", []),
            "source": source,
        })
    return paths


def load_path(path_id):
    for _, path_file in _path_files():
        entry = os.path.basename(os.path.dirname(path_file))
        with open(path_file) as f:
            data = yaml.safe_load(f) or {}
        if entry == path_id or data.get("id") == path_id:
            return data
    raise FileNotFoundError(f"Path not found: {path_id}")


def parse_path_yaml(text):
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"Template is not valid YAML: {e}")
    if not isinstance(data, dict):
        raise ValueError("Template must be a YAML mapping with id, version, name, params, items")
    return data


# --- Structural validation ---

def validate_path(path_def):
    """Return (errors, warnings).  Errors block saving and instantiation."""
    errors, warnings = [], []
    if not isinstance(path_def, dict):
        return ["Template must be a YAML mapping with id, version, name, params, items"], []

    for key in ("id", "version", "name", "items"):
        if not path_def.get(key):
            errors.append(f"Missing top-level field '{key}'")

    path_id = path_def.get("id")
    if path_id and not SLUG_RE.match(str(path_id)):
        errors.append(f"id '{path_id}' must be lowercase letters, digits, and dashes (e.g. 'garden-spring')")

    version = path_def.get("version")
    if version and not VERSION_RE.match(str(version)):
        errors.append(f"version '{version}' must look like \"1.0.0\" (quote it so YAML keeps it a string)")

    params = _check_params(path_def.get("params") or [], errors)
    used = set()

    items = path_def.get("items") or []
    if not isinstance(items, list):
        errors.append("items must be a list")
        items = []

    seen_refs = {}
    for i, item in enumerate(items):
        where = f"items[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: each item must be a mapping")
            continue
        if item.get("ref"):
            where = f"items[{i}] ({item['ref']})"
        _check_item(item, where, params, seen_refs, used, errors, warnings)

    for name in params:
        if name not in used:
            warnings.append(f"Param '{name}' is declared but never used")

    return errors, warnings


def _check_params(param_list, errors):
    params = {}
    if not isinstance(param_list, list):
        errors.append("params must be a list")
        return params
    for i, spec in enumerate(param_list):
        where = f"params[{i}]"
        if not isinstance(spec, dict):
            errors.append(f"{where}: each param must be a mapping with name and type")
            continue
        name = spec.get("name")
        if not name or not PARAM_NAME_RE.match(str(name)):
            errors.append(f"{where}: name '{name}' must be a plain identifier (e.g. frost_date_fall)")
            continue
        if name in params:
            errors.append(f"{where}: duplicate param '{name}'")
        if spec.get("type") not in PARAM_TYPES:
            errors.append(f"{where} ({name}): type must be one of {', '.join(PARAM_TYPES)}")
        params[name] = spec
    return params


def _check_item(item, where, params, seen_refs, used, errors, warnings):
    for key in item:
        if key in REJECTED_KEYS:
            errors.append(f"{where}: '{key}' — {REJECTED_KEYS[key]}")
        elif key not in ITEM_KEYS:
            errors.append(f"{where}: unknown field '{key}' (allowed: {', '.join(sorted(ITEM_KEYS))})")

    ref = item.get("ref")
    if not ref:
        errors.append(f"{where}: missing 'ref' (a short stable id like 'plant-garlic')")
    elif not SLUG_RE.match(str(ref)):
        errors.append(f"{where}: ref '{ref}' must be lowercase letters, digits, and dashes")
    elif ref in seen_refs:
        errors.append(f"{where}: duplicate ref '{ref}'")

    if not item.get("name"):
        errors.append(f"{where}: missing 'name'")

    per_entity = item.get("per_entity")
    if per_entity:
        used.add(per_entity)
        spec = params.get(per_entity)
        if not spec:
            errors.append(f"{where}: per_entity '{per_entity}' is not a declared param")
        elif spec.get("type") not in ("entity_ref", "list"):
            errors.append(f"{where}: per_entity '{per_entity}' must be an entity_ref or list param")

    for field in ("name", "description", "group"):
        _check_placeholders(item.get(field), f"{where}.{field}", params,
                            bool(per_entity), used, errors)

    checklist = item.get("checklist")
    if checklist is not None:
        if not isinstance(checklist, list):
            errors.append(f"{where}.checklist must be a list of {{label: ...}} entries")
        else:
            for j, entry in enumerate(checklist):
                if not isinstance(entry, dict) or not entry.get("label"):
                    errors.append(f"{where}.checklist[{j}] must be a mapping with a 'label'")
                    continue
                _check_placeholders(entry["label"], f"{where}.checklist[{j}]",
                                    params, bool(per_entity), used, errors)

    sort_order = item.get("sort_order")
    if sort_order is not None and not _is_int(sort_order):
        errors.append(f"{where}.sort_order must be an integer")

    if "trigger" not in item:
        errors.append(f"{where}: missing 'trigger'")
    else:
        _check_trigger(item["trigger"], f"{where}.trigger", params, seen_refs,
                       used, errors, warnings)

    if ref:
        seen_refs[ref] = per_entity


def _check_placeholders(text, where, params, entity_ok, used, errors):
    if not isinstance(text, str):
        return
    for key in PLACEHOLDER_RE.findall(text):
        if key == "entity" or key.startswith("entity."):
            if not entity_ok:
                errors.append(f"{where}: {{{key}}} only works on items with per_entity")
        elif key in params:
            used.add(key)
        else:
            errors.append(f"{where}: unknown placeholder {{{key}}} — declare '{key}' under params")


def _check_trigger(tdef, where, params, seen_refs, used, errors, warnings):
    if not isinstance(tdef, dict):
        errors.append(f"{where} must be a mapping with a 'type'")
        return
    ttype = tdef.get("type")
    if ttype not in TRIGGER_TYPES:
        errors.append(f"{where}: type '{ttype}' is not one of {', '.join(TRIGGER_TYPES)}")
        return

    for key in tdef:
        if key not in TRIGGER_KEYS[ttype]:
            errors.append(f"{where}: unknown field '{key}' for a {ttype} trigger "
                          f"(allowed: {', '.join(sorted(TRIGGER_KEYS[ttype]))})")

    if ttype == "calendar":
        if "date" not in tdef:
            errors.append(f"{where}: calendar trigger needs a 'date'")
        else:
            _check_date_field(tdef["date"], f"{where}.date", params, used, errors, warnings)
        if "prep_days" in tdef and not _is_int(tdef["prep_days"]):
            errors.append(f"{where}.prep_days must be a whole number (negative = days after the date)")

    elif ttype == "condition":
        rules = tdef.get("rules")
        if not isinstance(rules, list) or not rules:
            errors.append(f"{where}: condition trigger needs a non-empty 'rules' list")
            rules = []
        for k, rule in enumerate(rules):
            _check_rule(rule, f"{where}.rules[{k}]", errors)
        if "earliest_date" in tdef:
            _check_date_field(tdef["earliest_date"], f"{where}.earliest_date",
                              params, used, errors, warnings)

    elif ttype == "after":
        ref = tdef.get("item_ref")
        if not ref:
            errors.append(f"{where}: after trigger needs 'item_ref' (the ref of an earlier item)")
        elif ref not in seen_refs:
            errors.append(f"{where}: item_ref '{ref}' must be the ref of an item defined above this one")
        elif seen_refs[ref]:
            warnings.append(f"{where}: '{ref}' is created once per {seen_refs[ref]}; "
                            f"this item waits only on the last copy")
        event = tdef.get("event", "completed")
        if event != "completed":
            errors.append(f"{where}: event '{event}' is not supported yet — use 'completed'")
        if "offset_days" in tdef and (not _is_int(tdef["offset_days"]) or tdef["offset_days"] < 0):
            errors.append(f"{where}.offset_days must be a whole number of days, 0 or more")

    elif ttype == "compound":
        if tdef.get("op") not in ("and", "or"):
            errors.append(f"{where}: op must be 'and' or 'or'")
        subs = tdef.get("triggers")
        if not isinstance(subs, list) or len(subs) < 2:
            errors.append(f"{where}: compound trigger needs at least 2 triggers")
            subs = subs if isinstance(subs, list) else []
        for k, sub in enumerate(subs):
            _check_trigger(sub, f"{where}.triggers[{k}]", params, seen_refs,
                           used, errors, warnings)


def _check_rule(rule, where, errors):
    if not isinstance(rule, dict):
        errors.append(f"{where} must be a mapping with metric, operator, value")
        return
    for key in rule:
        if key not in RULE_KEYS:
            errors.append(f"{where}: unknown field '{key}' (allowed: {', '.join(sorted(RULE_KEYS))})")
    if rule.get("metric") not in METRICS:
        errors.append(f"{where}: metric '{rule.get('metric')}' is not one of "
                      f"{', '.join(METRICS)} (soil temperature and rain are not measured)")
    if rule.get("operator") not in OPERATORS:
        errors.append(f"{where}: operator '{rule.get('operator')}' is not one of "
                      f"{', '.join(OPERATORS)} (quote it in YAML)")
    value = rule.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{where}: value must be a number (°F)")
    if "sustained_days" in rule and (not _is_int(rule["sustained_days"]) or rule["sustained_days"] < 1):
        errors.append(f"{where}: sustained_days must be a whole number, 1 or more")


def _check_date_field(value, where, params, used, errors, warnings):
    if not isinstance(value, str):
        errors.append(f"{where}: dates must be quoted strings like \"2026-10-20\" or \"{{param}}\"")
        return
    m = WHOLE_PLACEHOLDER_RE.match(value)
    if m:
        name = m.group(1)
        if name not in params:
            errors.append(f"{where}: unknown placeholder {{{name}}} — declare '{name}' under params")
        else:
            used.add(name)
            if params[name].get("type") != "date":
                errors.append(f"{where}: param '{name}' must have type 'date' to be used as a date")
        return
    if not _is_date(value):
        errors.append(f"{where}: '{value}' is not a YYYY-MM-DD date or a single {{param}}")
        return
    warnings.append(f"{where}: hardcoded date {value} will not move next season — "
                    f"consider a date param")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# --- Parameter values ---

def apply_defaults(path_def, params):
    merged = dict(params or {})
    for spec in path_def.get("params") or []:
        if spec.get("name") not in merged and "default" in spec:
            merged[spec["name"]] = spec["default"]
    return merged


def validate_params(path_def, provided_params):
    """Check supplied values against declared params.  Returns (errors, warnings)."""
    errors, warnings = [], []
    declared = {}
    for spec in path_def.get("params") or []:
        name = spec["name"]
        declared[name] = spec
        if name not in provided_params:
            if spec.get("required", True) and "default" not in spec:
                errors.append(f"Missing required parameter: {name}")
            continue
        err = _check_value(spec, provided_params[name])
        if err:
            errors.append(f"Parameter '{name}': {err}")
    for name in provided_params:
        if name not in declared:
            warnings.append(f"Parameter '{name}' is not declared by this path and is ignored")
    return errors, warnings


def _check_value(spec, value):
    ptype = spec.get("type")
    if ptype == "date" and not _is_date(value):
        return f"'{value}' is not a YYYY-MM-DD date"
    if ptype == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        return f"'{value}' is not a number"
    if ptype in ("list", "entity_ref"):
        if not isinstance(value, list):
            return "must be a list"
        if ptype == "entity_ref":
            for entity in value:
                if not (isinstance(entity, str) or (isinstance(entity, dict) and entity.get("name"))):
                    return "each entity must be a name or a mapping with a 'name'"
    return None


# --- Expansion ---

def expand_items(path_def, params):
    """Expand item templates into concrete items, in insertion order.

    after-triggers still carry the path-local ref; instantiate() swaps
    them for real item IDs as it inserts.
    """
    expanded = []
    for tmpl in path_def.get("items", []):
        per_entity = tmpl.get("per_entity")
        entities = params.get(per_entity) if per_entity else None
        if isinstance(entities, list):
            for entity in entities:
                entity_ctx = entity if isinstance(entity, dict) else {"name": entity}
                expanded.append(_expand_one(tmpl, params, entity_ctx))
        else:
            expanded.append(_expand_one(tmpl, params, None))
    return expanded


def _expand_one(tmpl, params, entity_ctx):
    ctx = {**params}
    if entity_ctx:
        ctx["entity"] = entity_ctx
        # Flatten entity properties for {entity.name}, {entity.sun} etc.
        for k, v in entity_ctx.items():
            ctx[f"entity.{k}"] = v
            if isinstance(v, dict):
                for sk, sv in v.items():
                    ctx[f"entity.{k}.{sk}"] = sv

    ref = tmpl.get("ref", "")
    entity_name = entity_ctx.get("name", "") if entity_ctx else ""
    return {
        "ref": ref,
        "ref_key": f"{ref}:{entity_name}" if entity_ctx and ref else ref,
        "name": _substitute(tmpl["name"], ctx),
        "description": _substitute(tmpl.get("description", ""), ctx),
        "group": _substitute(tmpl.get("group", ""), ctx),
        "trigger": _substitute_tree(copy.deepcopy(tmpl["trigger"]), ctx),
        "checklist": _substitute_tree(copy.deepcopy(tmpl.get("checklist", [])), ctx),
        "sort_order": tmpl.get("sort_order", 0),
    }


def _substitute_tree(value, ctx):
    """Fill {param} placeholders in strings anywhere in a trigger or checklist."""
    if isinstance(value, str):
        return _substitute(value, ctx)
    if isinstance(value, list):
        return [_substitute_tree(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_tree(v, ctx) for k, v in value.items()}
    return value


def _substitute(template, ctx):
    if not template:
        return template

    def _fill(m):
        key = m.group(1)
        if key not in ctx or isinstance(ctx[key], (dict, list)):
            return m.group(0)
        return str(ctx[key])
    return PLACEHOLDER_RE.sub(_fill, template)


def leftover_placeholders(value):
    if isinstance(value, str):
        return PLACEHOLDER_RE.findall(value)
    if isinstance(value, list):
        return [p for v in value for p in leftover_placeholders(v)]
    if isinstance(value, dict):
        return [p for v in value.values() for p in leftover_placeholders(v)]
    return []


# --- Preview ---

def describe_trigger(tdef, ref_names=None, _nested=False):
    """Plain-English description of when a trigger fires."""
    ref_names = ref_names or {}
    ttype = tdef.get("type")

    if ttype == "calendar":
        date = tdef.get("date")
        prep = tdef.get("prep_days") or 0
        if not prep:
            return f"on {date}"
        relative = f"{abs(prep)} days {'before' if prep > 0 else 'after'} {date}"
        if _is_date(date):
            fire = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=prep)
            return f"on {fire.strftime('%Y-%m-%d')} ({relative})"
        return relative

    if ttype == "condition":
        parts = []
        for rule in tdef.get("rules", []):
            label = METRIC_LABELS.get(rule.get("metric"), rule.get("metric"))
            text = f"{label} {rule.get('operator')} {rule.get('value')}°F"
            days = rule.get("sustained_days", 1)
            if days and days > 1:
                text += f" for {days} days in a row"
            parts.append(text)
        text = "when " + " and ".join(parts)
        if tdef.get("earliest_date"):
            text += f", not before {tdef['earliest_date']}"
        return text

    if ttype == "after":
        ref = tdef.get("item_ref")
        name = ref_names.get(ref, ref)
        offset = tdef.get("offset_days") or 0
        if offset:
            return f"{offset} days after '{name}' is done"
        return f"when '{name}' is done"

    if ttype == "compound":
        joiner = " AND " if tdef.get("op") == "and" else " OR "
        text = joiner.join(describe_trigger(sub, ref_names, _nested=True)
                           for sub in tdef.get("triggers", []))
        return f"({text})" if _nested else text

    return f"unknown trigger type '{ttype}'"


def check_path(path_def, params=None):
    """Validate a template and, when params are given, preview what it creates.

    Returns {"valid", "errors", "warnings", "preview"}.  preview is None
    when params are not supplied or the template has errors.
    """
    errors, warnings = validate_path(path_def)
    result = {"valid": not errors, "errors": errors, "warnings": warnings,
              "preview": None}
    if errors or params is None:
        return result

    merged = apply_defaults(path_def, params)
    param_errors, param_warnings = validate_params(path_def, merged)
    errors.extend(param_errors)
    warnings.extend(param_warnings)
    if param_errors:
        result["valid"] = False
        return result

    items = expand_items(path_def, merged)
    ref_names = {item["ref"]: item["name"] for item in items}
    preview = []
    for item in items:
        leftovers = leftover_placeholders(
            [item["name"], item["description"], item["group"],
             item["trigger"], item["checklist"]])
        for key in sorted(set(leftovers)):
            errors.append(f"'{item['name']}': {{{key}}} has no value — "
                          f"give the param a default or make it required")
        preview.append({
            "ref": item["ref"],
            "name": item["name"],
            "group": item["group"],
            "when": describe_trigger(item["trigger"], ref_names),
            "checklist": [c.get("label") for c in item["checklist"]],
        })
    result["valid"] = not errors
    result["preview"] = preview
    return result


# --- Saving ---

def save_path(text):
    """Validate YAML text and write it as a custom template.  Returns the file path."""
    path_def = parse_path_yaml(text)
    errors, _ = validate_path(path_def)
    if errors:
        raise ValueError("Template has errors:\n  " + "\n  ".join(errors))

    path_id = path_def["id"]
    builtin = os.path.join(builtin_paths_dir(), path_id, "path.yaml")
    if os.path.isfile(builtin):
        raise ValueError(f"'{path_id}' is a built-in path. Give your template a different id.")

    target_dir = os.path.join(user_paths_dir(), path_id)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "path.yaml")
    with open(target, "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return target
