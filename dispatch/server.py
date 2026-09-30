"""dispatch.server — MCP server + HTTP API.

Supports three transport modes:
  --stdio   Stdio MCP (for Hermes plugins, Claude Desktop)
  --http    HTTP/SSE MCP (for Docker sidecar, network access)
  --api     HTTP API endpoints alongside MCP (eval, briefing, nudge, health)

Usage:
  dispatch serve --stdio                    # Hermes plugin / Claude Desktop
  dispatch serve --http --port 8082         # Docker sidecar, MCP only
  dispatch serve --http --port 8082 --api   # Docker sidecar, MCP + HTTP API
"""

import argparse
import json
import os
import sys

from mcp.server import Server
from mcp import types

from dispatch.store import (
    connect, get_item, get_items, get_open_items, get_due_items,
    transition, new_id, now_iso, row_to_dict, log_event, init_db,
)
from dispatch.resolve import resolve, format_code_list
from dispatch.instantiate import instantiate, list_paths
from dispatch.paths import check_path, load_path, parse_path_yaml, save_path


app = Server("dispatch")


def ok(data):
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(data, indent=2))],
    )


def err(message):
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"error": message}))],
        isError=True,
    )


# --- MCP Tool definitions ---

@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="status",
            description=(
                "Show open items across all domains with stable completion codes. "
                "Optionally filter by domain."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Filter by domain slug"},
                },
            },
        ),
        types.Tool(
            name="done",
            description=(
                "Complete an item by its code (e.g. G3), name substring, or ID. "
                "Returns the completed item or lists ambiguous matches."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Code, name, or ID"},
                    "domain": {"type": "string", "description": "Narrow search to domain"},
                    "notes": {"type": "string", "description": "Completion notes"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="skip",
            description=(
                "Skip an item by its code (e.g. H3), name substring, or ID. "
                "The item leaves the open list and is not marked done."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Code, name, or ID"},
                    "domain": {"type": "string", "description": "Narrow search to domain"},
                    "notes": {"type": "string", "description": "Why it was skipped"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="defer",
            description="Defer an item to a new date. Rewrites the trigger and returns to watching.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Code, name, or ID"},
                    "new_date": {"type": "string", "description": "New date YYYY-MM-DD"},
                    "reason": {"type": "string", "description": "Why deferred"},
                },
                "required": ["query", "new_date"],
            },
        ),
        types.Tool(
            name="note",
            description="Add a note or observation to an item.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Code, name, or ID"},
                    "text": {"type": "string", "description": "Note content"},
                },
                "required": ["query", "text"],
            },
        ),
        types.Tool(
            name="instantiate",
            description=(
                "Instantiate a path template into items for a domain. "
                "Use `status` to see available paths."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path_id": {"type": "string", "description": "Path template ID"},
                    "domain": {"type": "string", "description": "Domain slug"},
                    "params": {"type": "object", "description": "Path parameters"},
                },
                "required": ["path_id", "domain"],
            },
        ),
        types.Tool(
            name="draft_path",
            description=(
                "Validate a path template and preview the items it would create, "
                "with plain-English fire dates. Pass `yaml` for a new or edited "
                "template, or `path_id` to check an existing one. Nothing is "
                "written unless save=true and the template has no errors; saved "
                "templates can then be used with `instantiate`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "yaml": {"type": "string", "description": "Full path template as YAML text"},
                    "path_id": {"type": "string", "description": "Check an existing template instead"},
                    "params": {"type": "object", "description": "Sample parameters for the preview"},
                    "save": {"type": "boolean", "description": "Save as a custom template if valid"},
                },
            },
        ),
        types.Tool(
            name="undo",
            description="Undo the most recent batch of changes.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "status":
            return _status(arguments)
        elif name == "done":
            return _done(arguments)
        elif name == "skip":
            return _skip(arguments)
        elif name == "defer":
            return _defer(arguments)
        elif name == "note":
            return _note(arguments)
        elif name == "instantiate":
            return _instantiate(arguments)
        elif name == "draft_path":
            return _draft_path(arguments)
        elif name == "undo":
            return _undo(arguments)
        else:
            return err(f"Unknown tool: {name}")
    except Exception as e:
        return err(str(e))


# --- MCP tool handlers ---

def _status(args):
    domain = args.get("domain")
    with connect() as conn:
        items = get_open_items(conn, domain=domain)
        coded_from = get_items(conn, domain=domain)
    if not items:
        return ok({"message": "No open items", "items": []})

    code_list = format_code_list(items, code_source=coded_from)
    return ok({
        "count": len(items),
        "items": items,
        "formatted": code_list,
        "paths": list_paths(),
    })


def _done(args):
    query = args["query"]
    domain = args.get("domain")
    notes = args.get("notes", "")

    matches, exact = resolve(query, domain=domain)

    if not matches:
        return err(f"No match for '{query}'")

    if not exact:
        return err(
            f"Ambiguous — {len(matches)} matches. "
            "Be more specific or use the item code.\n"
            + "\n".join(f"  {m['id']}  {m['domain']}/{m['name']}" for m in matches)
        )

    item = matches[0]
    if item["status"] == "done":
        return err(f"'{item['name']}' is already done.")
    if item["status"] == "skipped":
        return err(f"'{item['name']}' is already skipped.")
    with connect() as conn:
        batch_id = new_id()
        updated = transition(conn, item["id"], "complete",
                             batch_id=batch_id, notes=notes)
    return ok({"completed": updated})


def _skip(args):
    query = args["query"]
    domain = args.get("domain")
    notes = args.get("notes", "")

    matches, exact = resolve(query, domain=domain)

    if not matches:
        return err(f"No match for '{query}'")

    if not exact:
        return err(
            f"Ambiguous — {len(matches)} matches. "
            "Be more specific or use the item code.\n"
            + "\n".join(f"  {m['id']}  {m['domain']}/{m['name']}" for m in matches)
        )

    item = matches[0]
    if item["status"] == "done":
        return err(f"'{item['name']}' is already done.")
    if item["status"] == "skipped":
        return err(f"'{item['name']}' is already skipped.")
    with connect() as conn:
        batch_id = new_id()
        updated = transition(conn, item["id"], "skip",
                             batch_id=batch_id, notes=notes)
    return ok({"skipped": updated})


def _defer(args):
    query = args["query"]
    new_date = args["new_date"]
    reason = args.get("reason", "")

    matches, exact = resolve(query)
    if not matches:
        return err(f"No match for '{query}'")
    if not exact:
        return err(
            f"Ambiguous — {len(matches)} matches.\n"
            + "\n".join(f"  {m['id']}  {m['domain']}/{m['name']}" for m in matches)
        )

    item = matches[0]
    with connect() as conn:
        batch_id = new_id()
        updated = transition(conn, item["id"], "defer",
                             batch_id=batch_id, new_date=new_date,
                             reason=reason)
    return ok({"deferred": updated, "new_date": new_date})


def _note(args):
    query = args["query"]
    text = args["text"]

    matches, exact = resolve(query)
    if not matches:
        return err(f"No match for '{query}'")
    if not exact:
        return err(
            f"Ambiguous — {len(matches)} matches.\n"
            + "\n".join(f"  {m['id']}  {m['domain']}/{m['name']}" for m in matches)
        )

    item = matches[0]
    with connect() as conn:
        old_notes = item.get("notes", "") or ""
        new_notes = (old_notes + "\n" + text).strip()
        conn.execute(
            "UPDATE items SET notes=?, updated_at=? WHERE id=?",
            (new_notes, now_iso(), item["id"]),
        )
        log_event(
            conn, "note_added",
            domain=item["domain"],
            item_id=item["id"],
            source_ref=item.get("source_ref"),
            old_values={"notes": old_notes},
            new_values={"notes": new_notes},
            payload={"text": text},
        )
        conn.commit()
    return ok({"item_id": item["id"], "notes": new_notes})


def _instantiate(args):
    path_id = args["path_id"]
    domain = args["domain"]
    params = args.get("params", {})

    ids = instantiate(path_id, domain, params)
    with connect() as conn:
        items = [get_item(conn, i) for i in ids]
    return ok({
        "path_id": path_id,
        "domain": domain,
        "items_created": len(ids),
        "items": items,
    })


def _draft_path(args):
    text = args.get("yaml")
    path_id = args.get("path_id")
    if not text and not path_id:
        return err("Pass either yaml (template text) or path_id (existing template)")
    if text and path_id:
        return err("Pass yaml or path_id, not both")

    path_def = parse_path_yaml(text) if text else load_path(path_id)
    result = check_path(path_def, args.get("params"))

    if args.get("save"):
        if not text:
            return err("save needs yaml; an existing template is already saved")
        result["saved_to"] = save_path(text)
    return ok(result)


def _undo(args):
    with connect() as conn:
        last_batch = conn.execute(
            "SELECT DISTINCT batch_id FROM event_log "
            "WHERE batch_id IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        if not last_batch:
            return err("Nothing to undo")

        batch_id = last_batch[0]
        events = conn.execute(
            "SELECT * FROM event_log WHERE batch_id=? ORDER BY timestamp DESC",
            (batch_id,),
        ).fetchall()

        undone = []
        for ev in events:
            ev = row_to_dict(ev)
            if ev.get("old_values") and ev.get("item_id"):
                old = ev["old_values"]
                if "status" in old:
                    conn.execute(
                        "UPDATE items SET status=?, updated_at=? WHERE id=?",
                        (old["status"], now_iso(), ev["item_id"]),
                    )
                    undone.append(ev["item_id"])

        log_event(
            conn, "item_undone",
            payload={"batch_id": batch_id, "items_undone": undone},
        )
        conn.commit()

    return ok({"undone_batch": batch_id, "items_reverted": undone})


# --- HTTP API (Starlette) ---

def create_http_app(enable_api=True):
    """Create a Starlette app with MCP SSE + optional HTTP API endpoints."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse, JSONResponse
    from starlette.routing import Route, Mount
    from mcp.server.sse import SseServerTransport

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read, write):
            await app.run(read, write, app.create_initialization_options())

    routes = [
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ]

    if enable_api:
        async def api_health(request):
            from dispatch.doctor import run_doctor
            return PlainTextResponse(run_doctor())

        async def api_eval(request):
            location = os.environ.get("DISPATCH_LOCATION", "")
            if not location:
                return JSONResponse({"error": "DISPATCH_LOCATION not set"}, status_code=400)
            from dispatch.eval import run_eval
            result = run_eval(location)
            return JSONResponse(result)

        async def api_briefing(request):
            from dispatch.briefing import build_briefing
            text = build_briefing()
            return PlainTextResponse(text or "")

        async def api_nudge(request):
            from dispatch.nudge import build_nudge
            text = build_nudge()
            return PlainTextResponse(text or "")

        async def api_status(request):
            domain = request.query_params.get("domain")
            with connect() as conn:
                items = get_open_items(conn, domain=domain)
                coded_from = get_items(conn, domain=domain)
            return JSONResponse({
                "count": len(items),
                "items": items,
                "formatted": format_code_list(items, code_source=coded_from) if items else "",
            })

        routes.extend([
            Route("/health", endpoint=api_health),
            Route("/api/eval", endpoint=api_eval, methods=["GET", "POST"]),
            Route("/api/briefing", endpoint=api_briefing),
            Route("/api/nudge", endpoint=api_nudge),
            Route("/api/status", endpoint=api_status),
        ])

    return Starlette(routes=routes)


# --- Entry points ---

async def run_stdio():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


def run_http(port=8082, host="0.0.0.0", enable_api=True):
    import uvicorn
    init_db()
    http_app = create_http_app(enable_api=enable_api)
    print(f"dispatch serving on {host}:{port} (MCP SSE at /sse"
          + (", API at /api/*" if enable_api else "") + ")",
          file=sys.stderr)
    uvicorn.run(http_app, host=host, port=port, log_level="info")


def main():
    parser = argparse.ArgumentParser(prog="dispatch serve")
    parser.add_argument("--stdio", action="store_true",
                        help="Stdio MCP transport (Hermes plugin, Claude Desktop)")
    parser.add_argument("--http", action="store_true",
                        help="HTTP/SSE MCP transport (Docker, network)")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--api", action="store_true",
                        help="Enable HTTP API endpoints (/api/eval, /api/briefing, etc.)")
    args = parser.parse_args()

    if args.http:
        run_http(port=args.port, host=args.host, enable_api=args.api)
    else:
        import asyncio
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
