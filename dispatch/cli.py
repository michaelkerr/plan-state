"""dispatch.cli — command-line interface.

Usage:
    dispatch init           Initialize the DB
    dispatch serve          Run MCP server (--stdio or --http)
    dispatch eval           Run full eval pipeline (weather + conditions + triggers)
    dispatch briefing       Generate morning briefing
    dispatch nudge          Generate evening nudge
    dispatch doctor         Health check
    dispatch status         Show open items with codes
    dispatch done <query>   Complete an item by code or name
    dispatch defer <query> <date>  Defer an item
    dispatch paths          List available path templates
    dispatch instantiate <path_id> <domain> [--param key=value ...]
    dispatch check-path <file|path_id> [--param key=value ...] [--save]
"""

import argparse
import json
import os
import sys

import yaml


def main():
    parser = argparse.ArgumentParser(prog="dispatch",
                                     description="Condition-aware execution engine")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize the database")

    serve_p = sub.add_parser("serve", help="Run MCP server")
    serve_p.add_argument("--stdio", action="store_true",
                         help="Stdio MCP (Hermes plugin, Claude Desktop)")
    serve_p.add_argument("--http", action="store_true",
                         help="HTTP/SSE MCP (Docker, network)")
    serve_p.add_argument("--port", type=int, default=8082)
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--api", action="store_true",
                         help="Enable HTTP API endpoints")

    eval_p = sub.add_parser("eval", help="Run eval pipeline")
    eval_p.add_argument("--location", default=os.environ.get("DISPATCH_LOCATION", ""))
    sub.add_parser("briefing", help="Generate morning briefing")
    sub.add_parser("nudge", help="Generate evening nudge")
    sub.add_parser("doctor", help="Health check")
    sub.add_parser("status", help="Show open items with codes")

    done_p = sub.add_parser("done", help="Complete an item")
    done_p.add_argument("query", help="Item code (G3), name, or ID")
    done_p.add_argument("--domain", default=None)
    done_p.add_argument("--notes", default="")

    defer_p = sub.add_parser("defer", help="Defer an item")
    defer_p.add_argument("query", help="Item code, name, or ID")
    defer_p.add_argument("date", help="New date (YYYY-MM-DD)")
    defer_p.add_argument("--reason", default="")

    sub.add_parser("paths", help="List available path templates")

    inst_p = sub.add_parser("instantiate", help="Instantiate a path")
    inst_p.add_argument("path_id", help="Path template ID")
    inst_p.add_argument("domain", help="Domain slug")
    inst_p.add_argument("--param", action="append", default=[],
                        help="Parameter as key=value (repeatable)")
    inst_p.add_argument("--params-file", default=None,
                        help="YAML/JSON file with parameters")

    check_p = sub.add_parser("check-path",
                             help="Validate a path template and preview its items")
    check_p.add_argument("target", help="Template file (path.yaml) or existing path ID")
    check_p.add_argument("--param", action="append", default=[],
                         help="Sample parameter as key=value (repeatable)")
    check_p.add_argument("--params-file", default=None,
                         help="YAML/JSON file with sample parameters")
    check_p.add_argument("--save", action="store_true",
                         help="Save the file as a custom template if valid")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        _cmd_init()
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "eval":
        _cmd_eval(args)
    elif args.command == "briefing":
        _cmd_briefing()
    elif args.command == "nudge":
        _cmd_nudge()
    elif args.command == "doctor":
        _cmd_doctor()
    elif args.command == "status":
        _cmd_status()
    elif args.command == "done":
        _cmd_done(args)
    elif args.command == "defer":
        _cmd_defer(args)
    elif args.command == "paths":
        _cmd_paths()
    elif args.command == "instantiate":
        _cmd_instantiate(args)
    elif args.command == "check-path":
        _cmd_check_path(args)


def _cmd_init():
    from dispatch.store import init_db
    path = init_db()
    print(f"Database initialized at {path}")


def _cmd_serve(args):
    if args.http:
        from dispatch.server import run_http
        run_http(port=args.port, host=args.host, enable_api=args.api)
    else:
        from dispatch.server import run_stdio
        import asyncio
        asyncio.run(run_stdio())


def _cmd_eval(args):
    location = args.location
    if not location:
        print("Error: --location required or set DISPATCH_LOCATION", file=sys.stderr)
        sys.exit(1)
    from dispatch.eval import run_eval
    results = run_eval(location)
    print(json.dumps(results, indent=2))


def _cmd_briefing():
    from dispatch.briefing import build_briefing
    text = build_briefing()
    if text:
        print(text)
    else:
        print("(nothing to report)", file=sys.stderr)


def _cmd_nudge():
    from dispatch.nudge import build_nudge
    text = build_nudge()
    if text:
        print(text)


def _cmd_doctor():
    from dispatch.doctor import run_doctor
    print(run_doctor())


def _cmd_status():
    from dispatch.store import connect
    from dispatch.resolve import format_code_list, _assign_codes

    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM items WHERE status IN (\'watching\',\'due\') '
            'ORDER BY domain, "group", sort_order, due_date',
        ).fetchall()
        from dispatch.store import row_to_dict
        items = [row_to_dict(r) for r in rows]

    if not items:
        print("No open items.")
        return

    print(format_code_list(items))


def _cmd_done(args):
    from dispatch.resolve import resolve
    from dispatch.store import connect, transition, new_id

    matches, exact = resolve(args.query, domain=args.domain)

    if not matches:
        print(f"No match for '{args.query}'", file=sys.stderr)
        sys.exit(1)

    if not exact:
        print(f"Ambiguous — {len(matches)} matches:")
        for m in matches:
            print(f"  {m['id']}  {m['domain']}/{m['name']}")
        sys.exit(1)

    item = matches[0]
    with connect() as conn:
        batch_id = new_id()
        updated = transition(conn, item["id"], "complete",
                             batch_id=batch_id, notes=args.notes)
    print(f"Done: {updated['name']} [{updated['id']}]")


def _cmd_defer(args):
    from dispatch.resolve import resolve
    from dispatch.store import connect, transition, new_id

    matches, exact = resolve(args.query)
    if not matches:
        print(f"No match for '{args.query}'", file=sys.stderr)
        sys.exit(1)
    if not exact:
        print(f"Ambiguous — {len(matches)} matches:")
        for m in matches:
            print(f"  {m['id']}  {m['domain']}/{m['name']}")
        sys.exit(1)

    item = matches[0]
    with connect() as conn:
        batch_id = new_id()
        updated = transition(conn, item["id"], "defer",
                             batch_id=batch_id, new_date=args.date,
                             reason=args.reason)
    print(f"Deferred: {updated['name']} → {args.date}")


def _cmd_paths():
    from dispatch.instantiate import list_paths
    paths = list_paths()
    if not paths:
        print("No paths found.")
        return
    for p in paths:
        print(f"  {p['id']}@{p['version']}  {p['name']}")
        if p.get("description"):
            print(f"    {p['description']}")
        if p.get("params"):
            names = [pp["name"] for pp in p["params"]]
            print(f"    params: {', '.join(names)}")


def _parse_params(args):
    params = {}
    # Parse --param key=value args
    for p in args.param:
        if "=" in p:
            k, v = p.split("=", 1)
            # Try to parse as JSON for lists/dicts
            try:
                params[k] = json.loads(v)
            except json.JSONDecodeError:
                params[k] = v

    # Load params file if provided
    if args.params_file:
        with open(args.params_file) as f:
            if args.params_file.endswith(".json"):
                file_params = json.load(f)
            else:
                file_params = yaml.safe_load(f)
            params.update(file_params)
    return params


def _cmd_instantiate(args):
    from dispatch.instantiate import instantiate

    params = _parse_params(args)
    ids = instantiate(args.path_id, args.domain, params)
    print(f"Instantiated {len(ids)} items from {args.path_id} into domain '{args.domain}'")
    for item_id in ids:
        print(f"  {item_id}")


def _cmd_check_path(args):
    from dispatch.paths import check_path, load_path, parse_path_yaml, save_path

    text = None
    if os.path.isfile(args.target):
        with open(args.target) as f:
            text = f.read()
        path_def = parse_path_yaml(text)
    else:
        path_def = load_path(args.target)

    params = _parse_params(args)
    result = check_path(path_def, params if (args.param or args.params_file) else None)

    for e in result["errors"]:
        print(f"ERROR    {e}")
    for w in result["warnings"]:
        print(f"WARNING  {w}")
    if result["preview"]:
        print("\nWould create:")
        for item in result["preview"]:
            group = f"[{item['group']}] " if item["group"] else ""
            print(f"  {group}{item['name']}")
            print(f"      due {item['when']}")
    elif not result["errors"]:
        print("Structure OK. Pass --param or --params-file to preview the items.")

    if result["errors"]:
        sys.exit(1)
    if args.save:
        if text is None:
            print("--save needs a template file", file=sys.stderr)
            sys.exit(1)
        print(f"\nSaved to {save_path(text)}")


if __name__ == "__main__":
    main()
