"""dispatch.doctor — health check.

Validates setup: DB path, last eval time, weather key, open item count.
"""

import os
from datetime import datetime, timedelta

from dispatch.store import connect, db_path


def run_doctor():
    checks = []

    # 1. DB exists and is readable
    path = db_path()
    if os.path.exists(path):
        checks.append(("DB exists", "ok", path))
    else:
        checks.append(("DB exists", "FAIL", f"Not found: {path}"))
        return _format(checks)

    with connect() as conn:
        # 2. Tables exist
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        expected = {"items", "event_log", "weather_log", "conditions_cache"}
        missing = expected - set(tables)
        if missing:
            checks.append(("Schema", "FAIL", f"Missing tables: {missing}"))
        else:
            checks.append(("Schema", "ok", f"{len(tables)} tables"))

        # 3. Item counts
        total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        watching = conn.execute(
            "SELECT COUNT(*) FROM items WHERE status='watching'"
        ).fetchone()[0]
        due = conn.execute(
            "SELECT COUNT(*) FROM items WHERE status='due'"
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM items WHERE status='done'"
        ).fetchone()[0]
        checks.append(("Items", "ok",
                        f"{total} total ({watching} watching, {due} due, {done} done)"))

        # 4. Last eval (most recent weather snapshot event)
        last_eval = conn.execute(
            "SELECT timestamp FROM event_log "
            "WHERE event_type='weather_snapshot' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if last_eval:
            ts = last_eval[0]
            checks.append(("Last eval", "ok", ts))
            try:
                last_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age = datetime.now(last_dt.tzinfo) - last_dt
                if age > timedelta(hours=2):
                    checks.append(("Eval freshness", "WARN",
                                   f"{age} since last eval (expected hourly)"))
                else:
                    checks.append(("Eval freshness", "ok", f"{age} ago"))
            except Exception:
                checks.append(("Eval freshness", "WARN", "Could not parse timestamp"))
        else:
            checks.append(("Last eval", "WARN", "No eval has run yet"))

        # 5. Weather API key
        owm = os.environ.get("OWM_API_KEY", "")
        if owm:
            checks.append(("OWM_API_KEY", "ok", f"Set ({len(owm)} chars)"))
        else:
            checks.append(("OWM_API_KEY", "WARN", "Not set — weather eval will skip"))

        # 6. Domains in use
        domains = conn.execute(
            "SELECT DISTINCT domain FROM items"
        ).fetchall()
        domain_list = [r[0] for r in domains]
        checks.append(("Domains", "ok", ", ".join(domain_list) if domain_list else "none"))

    return _format(checks)


def _format(checks):
    lines = ["dispatch doctor", "=" * 40]
    for name, status, detail in checks:
        marker = "✓" if status == "ok" else ("⚠" if status == "WARN" else "✗")
        lines.append(f"  {marker} {name}: {detail}")
    lines.append("=" * 40)
    ok = sum(1 for _, s, _ in checks if s == "ok")
    warn = sum(1 for _, s, _ in checks if s == "WARN")
    fail = sum(1 for _, s, _ in checks if s == "FAIL")
    lines.append(f"  {ok} ok, {warn} warn, {fail} fail")
    return "\n".join(lines)
