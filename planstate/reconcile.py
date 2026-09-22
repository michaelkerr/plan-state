"""planstate.reconcile — drift detection.

Compares dispatch items against domain context.  Flags items that
exist in dispatch but not in the context (orphaned), items in the
context that should have dispatch items but don't (missing), and
items whose dispatch status contradicts context state.
"""

from dispatch.store import connect, get_items, row_to_dict
from planstate.context import load_context, get_entities


def reconcile(domain):
    ctx = load_context(domain)
    with connect() as conn:
        items = get_items(conn, domain=domain)

    issues = []

    # Check for orphaned dispatch items (source_ref not in context entities)
    context_refs = _build_ref_set(ctx)
    for item in items:
        ref = item.get("source_ref", "")
        if ref and ref not in context_refs and ":" in ref:
            entity_part = ref.split(":", 1)[1] if ":" in ref else ref
            if entity_part and entity_part not in context_refs:
                issues.append({
                    "type": "orphaned_item",
                    "severity": "warn",
                    "item_id": item["id"],
                    "item_name": item["name"],
                    "source_ref": ref,
                    "message": f"Item '{item['name']}' references '{ref}' "
                               "which is not in the domain context",
                })

    # Check for completed items that context still shows as active
    for item in items:
        if item["status"] == "done":
            ref = item.get("source_ref", "")
            if ref:
                entity_name = ref.split(":", 1)[1] if ":" in ref else None
                if entity_name:
                    for entity in ctx.get("entities", []):
                        if entity.get("name") == entity_name:
                            state = entity.get("state", "")
                            if state and state not in ("done", "completed",
                                                       "harvesting",
                                                       "post-harvest"):
                                issues.append({
                                    "type": "state_mismatch",
                                    "severity": "info",
                                    "item_name": item["name"],
                                    "entity": entity_name,
                                    "dispatch_status": "done",
                                    "context_state": state,
                                    "message": (
                                        f"Item '{item['name']}' is done in dispatch "
                                        f"but entity '{entity_name}' is still "
                                        f"'{state}' in context"
                                    ),
                                })

    # Check for stale items (watching for a long time with no progress)
    from datetime import datetime, timedelta
    stale_threshold = (datetime.now() - timedelta(days=30)).isoformat()
    for item in items:
        if (item["status"] == "watching"
                and item.get("created_at", "") < stale_threshold
                and not item.get("trigger_fired")):
            issues.append({
                "type": "stale_item",
                "severity": "info",
                "item_id": item["id"],
                "item_name": item["name"],
                "created_at": item.get("created_at"),
                "message": f"Item '{item['name']}' has been watching for >30 days",
            })

    # Summary
    return {
        "domain": domain,
        "dispatch_items": len(items),
        "context_entities": len(ctx.get("entities", [])),
        "issues": issues,
        "issue_count": len(issues),
    }


def _build_ref_set(ctx):
    refs = set()
    for entity in ctx.get("entities", []):
        refs.add(entity.get("name", ""))
        refs.add(entity.get("type", "") + ":" + entity.get("name", ""))
    return refs
