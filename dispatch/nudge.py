"""dispatch.nudge — evening nudge generator.

Lists anything still open as of today.  Silent when nothing is due.
Includes stable completion codes so the user can reply "done G3".
"""

from datetime import datetime

from dispatch.store import connect, get_items
from dispatch.resolve import format_code_list


def build_nudge(today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")

    with connect() as conn:
        all_items = get_items(conn)

    due = [item for item in all_items
           if item["status"] == "due"
           and item.get("due_date") and item["due_date"] <= today]

    if not due:
        return ""

    header = f"Still open — {_short_date(today)}"
    body = format_code_list(due, code_source=all_items)
    footer = "\nReply `done <code>` to close, `skip <code>` to drop."
    return f"**{header}**\n{body}\n{footer}"


def _short_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %-d")
