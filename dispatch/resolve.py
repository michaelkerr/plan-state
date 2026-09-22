"""dispatch.resolve — completion resolver.

Resolves a user's free-text or shortcode input to a specific item for
completion.  The nudge/briefing emit stable codes (e.g. "G3") and this
module matches against them, or does substring/fuzzy match on names.

Goal: one tool call to close a task, confirm-if-ambiguous.
"""

from dispatch.store import connect, get_open_items, row_to_dict


def resolve(query, domain=None):
    """Resolve a query string to zero or more candidate items.

    Returns (matches, exact) where:
      - matches: list of item dicts
      - exact: True if exactly one unambiguous match
    """
    with connect() as conn:
        open_items = get_open_items(conn, domain=domain)

    if not open_items:
        return [], False

    # Assign stable codes: domain initial + index within domain
    coded = _assign_codes(open_items)

    # Try exact code match first (e.g. "G3", "L1", "H5")
    query_upper = query.strip().upper()
    for item, code in coded:
        if code == query_upper:
            return [item], True

    # Try exact ID match
    for item, _ in coded:
        if item["id"] == query.strip():
            return [item], True

    # Try exact name match (case-insensitive)
    query_lower = query.strip().lower()
    exact_name = [item for item, _ in coded
                  if item["name"].lower() == query_lower]
    if len(exact_name) == 1:
        return exact_name, True

    # Substring match on name
    substr = [item for item, _ in coded
              if query_lower in item["name"].lower()]
    if len(substr) == 1:
        return substr, True
    if substr:
        return substr, False

    # Substring match on group
    group_match = [item for item, _ in coded
                   if item.get("group") and query_lower in item["group"].lower()]
    if len(group_match) == 1:
        return group_match, True
    if group_match:
        return group_match, False

    return [], False


def _assign_codes(items):
    """Assign stable shortcodes: uppercase first letter of domain + index.

    Items are already sorted by domain/group/sort_order from get_open_items.
    Codes are deterministic for a given set of open items.
    """
    coded = []
    domain_counters = {}
    for item in items:
        domain = item.get("domain", "x")
        prefix = domain[0].upper() if domain else "X"
        count = domain_counters.get(domain, 0) + 1
        domain_counters[domain] = count
        code = f"{prefix}{count}"
        coded.append((item, code))
    return coded


def format_code_list(items):
    """Format open items with their stable codes for display in nudge/briefing."""
    coded = _assign_codes(items)
    lines = []
    current_domain = None
    for item, code in coded:
        if item["domain"] != current_domain:
            current_domain = item["domain"]
            lines.append(f"\n**{current_domain.title()}**")
        status_marker = "!" if item["status"] == "due" else "~"
        name = item["name"]
        group = item.get("group")
        if group:
            name = f"{group}: {name}"
        due = f" (due {item['due_date']})" if item.get("due_date") else ""
        lines.append(f"  {status_marker} [{code}] {name}{due}")
    return "\n".join(lines)
