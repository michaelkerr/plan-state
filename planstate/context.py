"""planstate.context — domain context management.

Loads, validates, and writes domain context files.  The domain context
schema is entity-agnostic: beds, stands, zones are all just entities
with types, names, properties, and optional lifecycle states.
"""

import os
import yaml
from datetime import datetime


CONTEXT_DIR = os.environ.get(
    "PLANSTATE_CONTEXT_DIR",
    os.path.expanduser("~/.plansync/domains"),
)


def load_context(domain):
    path = _context_path(domain)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No context for domain '{domain}' at {path}")
    with open(path) as f:
        ctx = yaml.safe_load(f)
    errors = validate_context(ctx)
    if errors:
        raise ValueError(f"Invalid context for '{domain}': " + "; ".join(errors))
    return ctx


def save_context(ctx):
    errors = validate_context(ctx)
    if errors:
        raise ValueError("Invalid context: " + "; ".join(errors))
    domain = ctx["domain"]
    path = _context_path(domain)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ctx["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(path, "w") as f:
        yaml.dump(ctx, f, default_flow_style=False, sort_keys=False)
    return path


def list_contexts():
    if not os.path.isdir(CONTEXT_DIR):
        return []
    contexts = []
    for entry in sorted(os.listdir(CONTEXT_DIR)):
        if entry.endswith(".yaml") or entry.endswith(".yml"):
            try:
                ctx = load_context(entry.rsplit(".", 1)[0])
                contexts.append({
                    "domain": ctx["domain"],
                    "display_name": ctx.get("display_name", ctx["domain"]),
                    "entity_count": len(ctx.get("entities", [])),
                    "active_paths": [p.get("path_id", "?")
                                     for p in ctx.get("active_paths", [])],
                })
            except Exception:
                pass
    return contexts


def validate_context(ctx):
    errors = []
    if not isinstance(ctx, dict):
        return ["Context must be a dict"]
    if "domain" not in ctx:
        errors.append("Missing required field: domain")
    if "location" not in ctx:
        errors.append("Missing required field: location")
    elif not isinstance(ctx["location"], dict):
        errors.append("location must be a dict with at least 'name'")
    elif "name" not in ctx["location"]:
        errors.append("location.name is required")

    for i, entity in enumerate(ctx.get("entities", [])):
        if not isinstance(entity, dict):
            errors.append(f"entities[{i}] must be a dict")
            continue
        if "type" not in entity:
            errors.append(f"entities[{i}] missing 'type'")
        if "name" not in entity:
            errors.append(f"entities[{i}] missing 'name'")

    return errors


def get_entity(ctx, entity_type=None, entity_name=None):
    for entity in ctx.get("entities", []):
        if entity_type and entity.get("type") != entity_type:
            continue
        if entity_name and entity.get("name") != entity_name:
            continue
        return entity
    return None


def get_entities(ctx, entity_type=None):
    return [e for e in ctx.get("entities", [])
            if entity_type is None or e.get("type") == entity_type]


def update_entity_state(ctx, entity_name, new_state):
    for entity in ctx.get("entities", []):
        if entity.get("name") == entity_name:
            entity["state"] = new_state
            return True
    return False


def record_path_activation(ctx, path_id, params):
    if "active_paths" not in ctx:
        ctx["active_paths"] = []
    ctx["active_paths"].append({
        "path_id": path_id,
        "instantiated_at": datetime.now().isoformat(timespec="seconds"),
        "params_used": params,
    })


def _context_path(domain):
    return os.path.join(CONTEXT_DIR, f"{domain}.yaml")
