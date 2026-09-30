"""dispatch.instantiate — path template instantiation.

Validates a path template, expands it with the supplied parameters,
and inserts the resulting items into the dispatch store.
"""

from dispatch.paths import (
    apply_defaults, expand_items, list_paths, load_path, validate_params,
    validate_path,
)
from dispatch.store import connect, insert_item, derive_conditions, log_event, new_id

__all__ = ["instantiate", "list_paths", "load_path"]


def instantiate(path_id, domain, params, conn=None):
    path_def = load_path(path_id)

    errors, _ = validate_path(path_def)
    if errors:
        raise ValueError(f"Path '{path_id}' is invalid: " + "; ".join(errors))

    params = apply_defaults(path_def, params)
    errors, _ = validate_params(path_def, params)
    if errors:
        raise ValueError("Parameter errors: " + "; ".join(errors))

    version = path_def.get("version", "0.0.0")
    full_path_id = f"{path_def.get('id', path_id)}@{version}"
    items = expand_items(path_def, params)

    def _do_insert(c):
        batch_id = new_id()
        ref_to_id = {}
        created_ids = []

        for item in items:
            trigger_def = _resolve_trigger_refs(item["trigger"], ref_to_id)
            item_id = insert_item(
                c, domain, item["name"], trigger_def,
                description=item["description"],
                source_ref=item["ref_key"],
                path_id=full_path_id,
                group=item["group"],
                checklist=item["checklist"],
                sort_order=item["sort_order"],
            )
            derive_conditions(c, item_id, trigger_def)

            if item["ref"]:
                ref_to_id[item["ref_key"]] = item_id
                ref_to_id[item["ref"]] = item_id
            created_ids.append(item_id)

            log_event(
                c, "item_created", batch_id=batch_id,
                domain=domain, item_id=item_id, source_ref=item["ref_key"],
                payload={"name": item["name"], "path_id": full_path_id},
            )

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
    with connect() as c:
        return _do_insert(c)


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
