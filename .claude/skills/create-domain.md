---
name: create-domain
description: Run a domain planning conversation and produce a validated domain definition JSON file for plan-state
user_invocable: true
---

# Create Domain

You are helping the user create a complete domain plan for the plan-state activity orchestrator. Your job is to have a planning conversation, then produce a validated JSON definition file that can be loaded into the system.

## Setup

1. Read `domain_schema.json` for the schema spec
2. Read one example from `examples/` for reference
3. Read `skills/domain-authoring.md` for the conversation guide and trigger reference

## Conversation

Ask the user about their domain. Key things to extract:

- **Domain name and location** (city,ST,US format for weather API)
- **Activities**: what needs to happen, and when
- **Triggers**: fixed date? weather condition? after another activity completes? Prefer compound triggers (calendar + condition) over pure condition triggers.
- **Prep steps**: what needs to happen before each activity, and how many days ahead
- **Follow-up steps**: what needs to happen after, and how many days later
- **Dependencies**: does any activity depend on another completing first?

Probe for things the user might forget:
- Supply ordering lead times
- Equipment maintenance
- Conditional steps (only if inventory is low, etc.)
- Follow-up monitoring or watering

## Output

1. Produce the domain definition as JSON conforming to `domain_schema.json`
2. Validate it by running: `python3 -c "import json, jsonschema; schema=json.load(open('domain_schema.json')); defn=json.load(open('<output_file>')); jsonschema.validate(defn, schema); print('Valid')"` 
3. Save it to `examples/<domain-name-slug>.json`
4. Tell the user how to load it (see below)

## How to load the definition into plan-state

There are two paths:

### Option A: Load via Hermes (Telegram)
Message Gideon on Telegram:
```
Use the plansync tools. Call load_domain with this definition: <paste JSON>
```
Or if the file is accessible to the container:
```
Read /opt/plansync/examples/<filename>.json and call load_domain with its contents
```

### Option B: Load directly via the MCP server
If the Mac Mini is running and you have shell access:
```bash
# Pipe the definition through the MCP server directly
docker exec -i gideon-gateway python3 -c "
import json, sys
sys.path.insert(0, '/opt/plansync/mcp-server')
import server
server.DB_PATH = '/opt/plansync/plansync.db'
conn = server.get_db()
defn = json.load(open('/opt/plansync/examples/<filename>.json'))
result = server._load_domain(conn, {'definition': defn})
print(result[0].text)
conn.close()
"
```

### Option C: Load locally for testing
If you have a local plansync.db:
```bash
PLANSYNC_DB=./plansync.db python3 -c "
import json, sys
sys.path.insert(0, 'mcp-server')
import server
server.DB_PATH = './plansync.db'
conn = server.get_db()
defn = json.load(open('examples/<filename>.json'))
result = server._load_domain(conn, {'definition': defn})
print(result[0].text)
conn.close()
"
```

## Rules

- Use `activity_ref` (name string) for dependency triggers, not `activity_id`
- `lead_days` must be >= 0
- Don't include `status` or `id` fields — the system assigns those
- `soil_temp` metric is defined but always NULL (OpenWeatherMap limitation) — use `daily_high` as a proxy
- Prefer compound triggers over pure condition triggers — most weather-dependent activities have a "not before" date
