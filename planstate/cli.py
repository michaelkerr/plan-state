"""planstate.cli — command-line interface for plan-state.

Usage:
    plan-state context <domain>    Show domain context
    plan-state contexts            List all domain contexts
    plan-state reconcile <domain>  Compare dispatch items vs context
    plan-state validate <domain>   Validate a domain context file
"""

import argparse
import json
import sys

import yaml


def main():
    parser = argparse.ArgumentParser(
        prog="plan-state",
        description="Plan quality framework for dispatch",
    )
    sub = parser.add_subparsers(dest="command")

    ctx_p = sub.add_parser("context", help="Show domain context")
    ctx_p.add_argument("domain", help="Domain slug")

    sub.add_parser("contexts", help="List all domain contexts")

    rec_p = sub.add_parser("reconcile", help="Reconcile dispatch vs context")
    rec_p.add_argument("domain", help="Domain slug")

    val_p = sub.add_parser("validate", help="Validate a context file")
    val_p.add_argument("domain", help="Domain slug")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "context":
        _cmd_context(args)
    elif args.command == "contexts":
        _cmd_contexts()
    elif args.command == "reconcile":
        _cmd_reconcile(args)
    elif args.command == "validate":
        _cmd_validate(args)


def _cmd_context(args):
    from planstate.context import load_context
    try:
        ctx = load_context(args.domain)
        print(yaml.dump(ctx, default_flow_style=False, sort_keys=False))
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def _cmd_contexts():
    from planstate.context import list_contexts
    contexts = list_contexts()
    if not contexts:
        print("No domain contexts found.")
        return
    for c in contexts:
        paths = ", ".join(c.get("active_paths", [])) or "none"
        print(f"  {c['domain']}: {c['display_name']} "
              f"({c['entity_count']} entities, paths: {paths})")


def _cmd_reconcile(args):
    from planstate.reconcile import reconcile
    result = reconcile(args.domain)
    print(f"Domain: {result['domain']}")
    print(f"Dispatch items: {result['dispatch_items']}")
    print(f"Context entities: {result['context_entities']}")
    print(f"Issues found: {result['issue_count']}")
    for issue in result["issues"]:
        severity = issue["severity"].upper()
        print(f"  [{severity}] {issue['message']}")


def _cmd_validate(args):
    from planstate.context import load_context
    try:
        ctx = load_context(args.domain)
        print(f"Context for '{args.domain}' is valid.")
        print(f"  Entities: {len(ctx.get('entities', []))}")
        print(f"  Location: {ctx.get('location', {}).get('name', '?')}")
        print(f"  Params: {list(ctx.get('params', {}).keys())}")
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
