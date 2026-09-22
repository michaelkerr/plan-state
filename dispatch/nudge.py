"""dispatch.nudge — evening nudge generator.

Lists anything still open as of today.  Silent when nothing is due.
Includes stable completion codes so the user can reply "done G3".
"""

from datetime import datetime

from dispatch.store import connect, row_to_dict
from dispatch.resolve import format_code_list


def build_nudge(today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")

    with connect() as conn:
        due = conn.execute(
            "SELECT * FROM items WHERE status='due' AND due_date <= ? "
            'ORDER BY domain, "group", sort_order',
            (today,),
        ).fetchall()
        due = [row_to_dict(r) for r in due]

    if not due:
        return ""

    header = f"Still open — {_short_date(today)}"
    body = format_code_list(due)
    footer = "\nReply `done <code>` to close."
    return f"**{header}**\n{body}\n{footer}"


def _short_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %-d")
