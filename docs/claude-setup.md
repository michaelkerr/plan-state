# Claude Desktop

Two pieces: the MCP server (tools) and the skills (how to talk).

## MCP server

**Docker Compose** (from this repo's `docker compose up -d`):

```json
{
  "mcpServers": {
    "dispatch": {
      "url": "http://127.0.0.1:8082/sse"
    }
  }
}
```

**Local install** (`pip install -e .`):

```json
{
  "mcpServers": {
    "dispatch": {
      "command": "dispatch",
      "args": ["serve", "--stdio"],
      "env": {
        "OWM_API_KEY": "your-key",
        "DISPATCH_LOCATION": "Nashville,TN,US",
        "DISPATCH_CLIENT": "claude",
        "DISPATCH_EVAL_MINUTES": "60"
      }
    }
  }
}
```

Config file: Claude → Settings → Developer → Edit Config
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS).
Restart Claude Desktop after editing.

You should see: `status`, `done`, `skip`, `defer`, `note`, `instantiate`,
`draft_path`, `undo`.

## Skills

```bash
mkdir -p ~/.claude/skills
cd /path/to/plan-state
for s in dispatch plan-state path-authoring briefing; do
  ln -sfn "$(pwd)/skills/$s" ~/.claude/skills/$s
done
```

These are the same files Hermes loads. Do not copy them — a symlink stays current.

## Verify

```bash
# Docker
curl -sf http://127.0.0.1:8082/health

# Local
dispatch doctor
```

Then in Claude: "what's open?" should call `status`.
