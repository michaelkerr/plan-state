"""dispatch.doctor — health check.

Validates setup (DB, weather key, location, templates) and live state
(items, last eval).  Every warning says what to do next, so a first-time
install can be finished from doctor's output alone.
"""

import os
from datetime import datetime, timedelta

from dispatch.store import connect, db_path

OWM_SIGNUP = "https://home.openweathermap.org/users/sign_up"


def run_doctor():
    checks = []

    # 1. DB exists and is readable
    path = db_path()
    if os.path.exists(path):
        checks.append(("DB exists", "ok", path))
    else:
        checks.append(("DB exists", "FAIL",
                       f"Not found: {path} — run `dispatch init` "
                       f"(or set DISPATCH_DB)"))
        _check_config(checks)
        return _format(checks)

    with connect() as conn:
        # 2. Tables exist
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        expected = {"items", "event_log", "weather_log", "conditions_cache"}
        missing = expected - set(tables)
        if missing:
            checks.append(("Schema", "FAIL",
                           f"Missing tables: {sorted(missing)} — run `dispatch init`"))
            _check_config(checks)
            return _format(checks)
        checks.append(("Schema", "ok", f"{len(tables)} tables"))

        _check_config(checks)

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
        if total:
            checks.append(("Items", "ok",
                           f"{total} total ({watching} watching, {due} due, {done} done)"))
        else:
            checks.append(("Items", "WARN",
                           "None yet — ask your agent to set up a domain, or run "
                           "`dispatch paths` then `dispatch instantiate`"))

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
                                   f"{_age(age)} since last eval (expected hourly) — "
                                   f"is the scheduler running?"))
                else:
                    checks.append(("Eval freshness", "ok", f"{_age(age)} ago"))
            except Exception:
                checks.append(("Eval freshness", "WARN", "Could not parse timestamp"))
        else:
            checks.append(("Last eval", "WARN",
                           "No eval has run yet — run `dispatch eval`, or serve "
                           "with --eval-every 60 / DISPATCH_EVAL_MINUTES=60"))

        # 5. Domains in use
        domains = conn.execute(
            "SELECT DISTINCT domain FROM items"
        ).fetchall()
        domain_list = [r[0] for r in domains]
        if domain_list:
            checks.append(("Domains", "ok", ", ".join(domain_list)))

    return _format(checks)


def _check_config(checks):
    owm = os.environ.get("OWM_API_KEY", "")
    if owm:
        checks.append(("OWM_API_KEY", "ok", f"Set ({len(owm)} chars)"))
    else:
        checks.append(("OWM_API_KEY", "WARN",
                       f"Not set — weather triggers will never fire. "
                       f"Free key: {OWM_SIGNUP}"))

    location = os.environ.get("DISPATCH_LOCATION", "")
    if location:
        checks.append(("DISPATCH_LOCATION", "ok", location))
    else:
        checks.append(("DISPATCH_LOCATION", "WARN",
                       "Not set — use 'City,ST,US' (e.g. 'Nashville,TN,US')"))

    from dispatch.paths import list_paths, user_paths_dir
    try:
        paths = list_paths()
    except Exception as e:
        checks.append(("Path templates", "FAIL", f"Could not read templates: {e}"))
        return
    builtin = sum(1 for p in paths if p["source"] == "built-in")
    custom = len(paths) - builtin
    if builtin:
        checks.append(("Path templates", "ok",
                       f"{builtin} built-in, {custom} custom ({user_paths_dir()})"))
    else:
        checks.append(("Path templates", "FAIL",
                       "No built-in templates found — check DISPATCH_PATHS_DIR"))


def _age(delta):
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min"
    return f"{hours // 24} days"


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
