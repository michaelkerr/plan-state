# Plan-State Synchronizer: MVP Spec (Hermes Agent Edition)

## What This Is

A three-part system that turns LLM-generated domain plans into managed, condition-aware Todoist tasks that re-cascade automatically when things slip, complete, or change.

**Conversational layer:** Hermes Agent (via Telegram, CLI, or any gateway platform) reads and writes structured plans to a SQLite store via a local MCP server.
**Middle:** SQLite database holds canonical plan state: activities, conditions, prep chains, dependencies, status, history.
**Downstream:** A no-agent cron job (deterministic Python, zero LLM involvement) pulls weather/conditions, evaluates triggers, re-cascades dates, and syncs the result to Todoist. An optional LLM cron job generates a morning briefing from the sync output.

## What Changed from the Original Spec

The original spec assumed Claude sessions via MCP as the conversational interface and a standalone system cron job for the sync loop. This version replaces both with a single Hermes Agent deployment running inside a Docker container on a home server.

| Original | Hermes Edition |
|---|---|
| Claude sessions + custom MCP server | Hermes Agent + same MCP server (Hermes as MCP client) |
| System cron at 6 AM | Hermes no-agent cron (deterministic script, zero tokens) |
| No notification system (Todoist only) | Hermes gateway delivers briefings to Telegram/Signal/etc. |
| No persistent conversational memory | Hermes cross-session memory + skill system |
| Three separate processes to manage | One Docker container |

The MCP server is retained. This is deliberate. Typed tool definitions with parameter schemas produce far more reliable LLM tool calls than "here's a CLI, figure out the flags." The MCP server also handles cascading, validation, and idempotency in deterministic Python rather than leaving it to inference.

## What This Tests

1. Does a structured plan store that Hermes can read/write eliminate the "plan dies in the chat transcript" problem?
2. Does daily condition checking + automatic date cascading solve the "right thing, wrong time" and "missed the prep window" failures?
3. Is Todoist a sufficient interaction surface for "now / next / later" across multiple domains?
4. Does Hermes's persistent memory + skill system reduce the friction of planning conversations compared to cold-start Claude sessions?

## Core User Flow

1. User messages Hermes via Telegram (or CLI, Discord, Signal, etc.).
2. User says: "Help me plan my fall garden succession for Zone 7a, beds 2 and 3, starting late August."
3. Hermes generates the plan AND writes it to the plan store via the plan-sync MCP tools. Activities, trigger conditions, prep steps with lead times, follow-up steps, dependencies.
4. Every morning at 6 AM, the no-agent cron job runs the sync script:
   - Pulls weather (current + 7-day forecast) for each location
   - Evaluates every "watching" activity's trigger conditions against current data
   - When a trigger fires: marks the activity "active," cascades prep step dates backward from trigger date
   - When a trigger date estimate shifts: re-cascades all dependent dates
   - When an activity or step is completed: cascades forward to follow-up steps and dependent activities
   - Syncs the result to Todoist: creates/updates/completes tasks, adjusts due dates, writes contextual descriptions
   - Writes a structured summary to stdout
5. At 6:15 AM, an optional LLM cron job runs with `--script` pointing at a summary-extraction script. The script reads today's sync output; the LLM generates a human-readable morning briefing; Hermes delivers it to Telegram.
6. User sees updated tasks in Todoist throughout the day. Completes them there (Todoist webhook or next-morning reconciliation syncs completions back to the plan store).
7. When something changes ("blossom end rot," "didn't get to the property," "frost came early"), user messages Hermes, discusses it, Hermes updates the plan store via MCP, next cron run re-cascades and re-syncs.

## Deployment: Docker Container

### Image and Compose

```yaml
services:
  hermes:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-plansync
    restart: unless-stopped
    command: gateway run
    ports:
      - "127.0.0.1:8642:8642"
    volumes:
      - ./hermes-data:/opt/data          # Hermes config, memory, skills, cron jobs
      - ./plansync-data:/opt/plansync     # SQLite DB, sync scripts, MCP server
    env_file:
      - .env
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2.0"
    networks:
      - plansync-net

networks:
  plansync-net:
    driver: bridge
```

### Environment (.env)

```bash
# LLM provider (pick one)
ANTHROPIC_API_KEY=sk-ant-...
# or: OPENROUTER_API_KEY=...
# or: NOUS_PORTAL_... (OAuth, auto-refresh)

# Messaging gateway
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_USERS=your_telegram_user_id
TELEGRAM_HOME_CHANNEL=your_chat_id

# Weather
OPENWEATHERMAP_API_KEY=...

# Todoist
TODOIST_API_KEY=...

# Timezone
TZ=America/New_York
```

### Volume Layout

```
./hermes-data/                  # mounted at /opt/data
  config.yaml                   # Hermes config (model, MCP servers, tools, etc.)
  .env                          # provider keys (alternative to top-level .env)
  skills/                       # Hermes skills (including plan-sync skill)
  scripts/                      # cron scripts
  cron/                         # cron job definitions (managed by Hermes)
  memory/                       # persistent memory store
  sessions/                     # conversation history

./plansync-data/                # mounted at /opt/plansync
  plansync.db                   # SQLite database (canonical plan state)
  mcp-server/                   # MCP server code
    server.py
    requirements.txt
  sync/                         # deterministic sync script
    daily_sync.py
    requirements.txt
```

The split between `hermes-data` and `plansync-data` is intentional. Hermes image upgrades (`docker pull && docker compose up -d`) should never risk the plan database or custom scripts. The plan store is Hermes-independent and could be pointed at by a different MCP client if Hermes doesn't work out.

### MCP Server Registration

In `hermes-data/config.yaml`:

```yaml
mcp_servers:
  plansync:
    command: python3
    args: ["/opt/plansync/mcp-server/server.py"]
    env:
      PLANSYNC_DB: "/opt/plansync/plansync.db"
```

Or via CLI after first boot:

```bash
docker exec -it hermes-plansync hermes mcp add plansync \
  --command python3 \
  --args "/opt/plansync/mcp-server/server.py" \
  --env PLANSYNC_DB=/opt/plansync/plansync.db
```

## Components

### 1. SQLite Schema

Identical to the original spec. Reproduced here for self-containedness.

```sql
CREATE TABLE domains (
  id              TEXT PRIMARY KEY,
  name            TEXT,        -- "Fall Garden", "Lawn Care", "Deer Hunting"
  location        TEXT,        -- used for weather queries
  notes           TEXT,        -- freeform context
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE activities (
  id              TEXT PRIMARY KEY,
  domain_id       TEXT REFERENCES domains(id),
  name            TEXT,        -- "Plant romaine succession"
  description     TEXT,        -- rich context for notification content
  status          TEXT DEFAULT 'watching',
                               -- watching | preparing | active | completed | skipped | deferred
  trigger_type    TEXT,        -- calendar | condition | dependency | compound
  trigger_def     JSON,        -- structured trigger definition
  trigger_date    DATE,        -- current best estimate (null if unknown)
  trigger_fired   DATETIME,
  completed_at    DATETIME,
  recurrence      JSON,        -- null, or recurrence rule for cyclical activities
  sort_order      INTEGER DEFAULT 0,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE steps (
  id              TEXT PRIMARY KEY,
  activity_id     TEXT REFERENCES activities(id),
  name            TEXT,        -- "Order romaine transplants"
  description     TEXT,
  step_type       TEXT,        -- prep | follow_up
  lead_days       INTEGER,     -- days before trigger (prep) or after completion (follow_up)
  status          TEXT DEFAULT 'pending',
                               -- pending | due | completed | skipped
  due_date        DATE,        -- computed from activity trigger_date +/- lead_days
  completed_at    DATETIME,
  condition       JSON,        -- optional: step only activates if condition met
  sort_order      INTEGER DEFAULT 0,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE conditions (
  id              TEXT PRIMARY KEY,
  activity_id     TEXT REFERENCES activities(id),
  condition_type  TEXT,        -- temperature | weather_event | calendar | dependency
  definition      JSON,
  current_value   REAL,
  is_met          BOOLEAN DEFAULT 0,
  last_checked    DATETIME
);

CREATE TABLE weather_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  location        TEXT,
  recorded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  temp_high       REAL,
  temp_low        REAL,
  soil_temp       REAL,
  conditions      TEXT,        -- rain, clear, overcast, etc.
  precipitation   REAL,        -- inches
  forecast_json   JSON
);

CREATE TABLE todoist_sync (
  plan_item_id    TEXT,
  plan_item_type  TEXT,        -- activity | step
  todoist_task_id TEXT,
  todoist_project TEXT,
  last_synced     DATETIME,
  sync_status     TEXT,        -- synced | pending_create | pending_update | pending_close
  PRIMARY KEY (plan_item_id, plan_item_type)
);

CREATE TABLE activity_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
  item_type       TEXT,        -- activity | step | condition
  item_id         TEXT,
  action          TEXT,        -- status_change | date_cascade | trigger_fire | manual_update
  old_value       JSON,
  new_value       JSON,
  source          TEXT         -- cron | hermes | todoist_webhook
);
```

Note: `source` column in `activity_log` changes from `mcp` to `hermes` to reflect the new conversational layer. Functionally identical.

### Trigger Definition Examples

Unchanged from original spec.

```json
// Calendar-based
{"type": "calendar", "date": "2026-08-25"}

// Condition-based
{"type": "condition", "all": [
  {"metric": "soil_temp", "operator": ">=", "value": 55, "sustained_days": 3},
  {"metric": "forecast_rain_in_days", "operator": "<=", "value": 2}
]}

// Dependency-based
{"type": "dependency", "activity_id": "bean-harvest-bed3", "event": "completed", "offset_days": 7}

// Compound
{"type": "compound", "operator": "AND", "conditions": [
  {"type": "calendar", "after": "2026-08-15"},
  {"type": "condition", "metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 3}
]}
```

### 2. MCP Server (stdio, Python)

A lightweight MCP server that Hermes connects to via stdio subprocess. Exposes the SQLite store as typed tools. Hermes uses these tools during planning conversations.

Implementation: Python, using the `mcp` SDK (`pip install mcp`). Runs as a child process of Hermes, communicates over stdin/stdout JSON-RPC.

**Tools:**

```
get_domains()
  Returns all domains with activity counts and status summary.

get_domain_plan(domain_id)
  Returns full plan: all activities, steps, conditions, current status,
  upcoming dates. This is what Hermes reads to understand current state
  before making changes.

create_activity(domain_id, name, description, trigger_def, steps[], ...)
  Creates an activity with its prep/follow-up steps and conditions.
  Returns the created activity with computed dates.

update_activity(activity_id, fields...)
  Modify trigger conditions, description, status, dates.
  Triggers re-cascade of dependent steps.

complete_activity(activity_id, notes?)
  Marks complete, cascades follow-up steps, activates dependent activities.

defer_activity(activity_id, new_date?, reason?)
  Pushes activity and re-cascades all steps.

create_domain(name, location, notes)
  Sets up a new domain.

add_observation(domain_id, observation_text, affects_activities[]?)
  Records a freeform observation (e.g., "blossom end rot on Early Girls").
  Optionally links to activities it might affect.
  Hermes can then decide whether to modify activities based on this.

get_upcoming(days_ahead=14)
  Cross-domain view: everything due or approaching trigger in the next N days.
  The "now / next / later" view.

get_weather_current(location)
  Returns latest weather data and 7-day forecast from the weather_log.
  Useful for Hermes to reference during planning sessions.
```

**What the MCP server does NOT do:** It does not evaluate conditions, cascade dates, or sync to Todoist. Those are the cron job's responsibility. The MCP server is a read/write interface to the plan store only. When Hermes creates an activity with a trigger_def, the trigger_date is computed on write if it's calendar-based, or left null if it's condition-based (the cron will evaluate it).

Exception: when Hermes explicitly sets or moves a date (e.g., user says "push the romaine planting to September 5"), the MCP server cascades steps immediately so Hermes can show the user the updated plan in the same conversation.

### 3. Daily Cron Job (No-Agent Mode)

Registered as a Hermes no-agent cron job. Runs the deterministic sync script at 6 AM. Zero LLM tokens consumed.

**Registration:**

```bash
hermes cron create "0 6 * * *" \
  --no-agent \
  --script daily-sync.py \
  --deliver telegram \
  --name "plan-sync"
```

The script lives at `~/.hermes/scripts/daily-sync.py` (inside the container: `/opt/data/scripts/daily-sync.py`). It has read/write access to the SQLite DB at `/opt/plansync/plansync.db`.

**What the script does** (same logic as original spec, same ordering):

**Step 1: Weather pull.**
Hit OpenWeatherMap for current conditions and 7-day forecast for each distinct location in the domains table. Store in weather_log.

**Step 2: Condition evaluation.**
For every condition in the conditions table, evaluate against current weather_log data. Update current_value, is_met, last_checked.

**Step 3: Trigger evaluation.**
For every activity in "watching" status:
- Calendar triggers: is the date within the prep window?
- Condition triggers: are all conditions met?
- Dependency triggers: has the upstream activity completed?
- Compound: evaluate recursively.

When a trigger fires:
- Set activity status to "preparing" (if prep steps exist) or "active" (if no prep)
- Set trigger_fired timestamp
- Compute prep step due dates
- Log the trigger fire in activity_log

**Step 4: Date re-cascade.**
For activities with condition-based triggers that haven't fired yet:
- Estimate trigger_date from current trends and forecast
- If estimated trigger_date changed from yesterday, re-cascade all step due dates
- Log the re-cascade

For activities whose upstream dependency shifted:
- Recompute trigger_date from the dependency's new estimated completion
- Re-cascade steps

**Step 5: Overdue check.**
For any step past its due_date that isn't completed:
- Flag as overdue in the plan store

**Step 6: Todoist sync.**
For every activity and step that has a due_date and status in {preparing, active, due, pending}:
- No todoist_task_id: create task, record mapping
- Dates or status changed: update task
- Completed in plan store: complete Todoist task
- Completed in Todoist (API poll): mark completed in plan store, cascade follow-ups

**Step 7: Summary output.**
Print a structured summary to stdout. This is what gets delivered to Telegram (if non-empty) and also saved to `/opt/plansync/sync-output/YYYY-MM-DD.json` for the optional briefing job to pick up.

```
Stdout format (example):
---
triggers_fired: 1
  - "Plant romaine succession" (condition: soil_temp >= 55 for 3 days)
dates_cascaded: 3
  - "Order romaine transplants" moved to Aug 18 (was Aug 20)
  - "Prep bed 3" moved to Aug 22 (was Aug 24)
  - "Plant romaine" moved to Aug 28 (was Aug 30)
todoist_created: 3
todoist_updated: 0
todoist_completed: 1
overdue: 0
---
```

Empty stdout (nothing happened) produces a silent tick with no Telegram delivery.

### 4. Morning Briefing (Optional LLM Cron Job)

Separate from the deterministic sync. Runs 15 minutes later, consumes LLM tokens, and produces a human-readable briefing.

```bash
hermes cron create "0 6 15 * * *" \
  --script briefing-context.sh \
  --deliver telegram \
  --skill plansync-briefing \
  --name "morning-briefing"
```

The `--script` runs `briefing-context.sh` first, which reads today's sync output JSON and the upcoming-14-days view from the DB. Its stdout becomes context for the LLM agent. The `plansync-briefing` skill instructs the agent to produce a concise, actionable morning summary.

This is the step where the original spec's FR-7.2 lives. The system works without it. Add it once the core sync loop is validated.

### 5. Hermes Skill: plan-sync

A skill document at `~/.hermes/skills/plansync.md` that teaches Hermes how to use the plan-sync MCP tools effectively during planning conversations.

```markdown
# Plan Sync Skill

You have access to the plan-sync MCP tools for managing domain plans.
These tools read/write a SQLite database that tracks activities,
conditions, prep steps, and Todoist sync state.

## Available Tools (via plansync MCP server)

- get_domains() -- list all domains
- get_domain_plan(domain_id) -- full plan state for a domain
- create_activity(...) -- create activity with steps and triggers
- update_activity(...) -- modify an existing activity
- complete_activity(...) -- mark done, cascade follow-ups
- defer_activity(...) -- push dates, re-cascade
- create_domain(...) -- new domain
- add_observation(...) -- record field observation
- get_upcoming(days_ahead) -- cross-domain upcoming view
- get_weather_current(location) -- latest weather + forecast

## Workflow

1. Always call get_domain_plan() before modifying a domain.
   Read current state first.
2. When creating activities, include all prep and follow-up steps
   with realistic lead_days.
3. For condition-based triggers, be specific about metrics,
   thresholds, and sustained_days requirements.
4. After modifications, call get_upcoming() to show the user
   what changed and what's coming up.
5. When the user reports a field observation, use add_observation()
   and then decide whether any activities need updating.

## Important

- The cron sync job handles condition evaluation and Todoist sync.
  Do NOT try to evaluate weather conditions or sync to Todoist
  during a planning conversation.
- Dates cascade automatically when you defer or update trigger_dates.
- If the user asks "what's coming up," call get_upcoming() rather
  than trying to reconstruct the schedule from memory.
```

This skill gets invoked automatically when Hermes detects plan-related conversation, or explicitly via `/skill plansync`.

### 6. Todoist Structure

Unchanged from original spec.

```
Todoist Project: "Garden - Fall 2026"
  Section: "Romaine Succession - Bed 3"
    Task: "Order romaine transplants" (due Aug 18)
    Task: "Prep bed 3 - clear bean debris" (due Aug 22)
    Task: "Plant romaine transplants" (due Aug 28)
    Task: "First harvest check" (due Oct 9)
  Section: "Late Tomato Harvest"
    Task: "Monitor for first frost forecast" (due Oct 15, recurring daily check)
    Task: "Strip mature-green fruit before hard freeze" (no date until frost forecast)

Todoist Project: "Lawn Care"
  Section: "Fall Pre-emergent"
    Task: "Order Barricade if < 4 lbs remaining" (due Aug 1)
    Task: "Apply pre-emergent" (due: TBD, watching soil temp)

Todoist Project: "Deer - 2026-27"
  Section: "Summer Prep"
    Task: "Cameras up, recon walk" (due Jun 15)
    Task: "Hang stands, weather blind" (due Aug 1)
    ...
```

Description on each task includes context Hermes wrote when creating the activity, plus dynamic context the cron job adds (current conditions, forecast, related activities).

## What NOT to Build

Everything from the original spec's "what not to build" list, plus:

- **Custom notification delivery system.** Hermes gateway handles this natively.
- **Hermes skills for condition evaluation.** The sync script handles this deterministically. Don't let the LLM do arithmetic.
- **Multi-container orchestration.** One container, one process tree. The MCP server runs as a subprocess.
- **Custom dashboard.** Hermes has a built-in dashboard; Todoist is the primary UI.
- **Webhook receiver.** Todoist completion sync happens via API polling in the daily cron job. If real-time sync proves necessary, add a simple webhook endpoint later, but start without it.

## Success / Failure Criteria

Same as original spec, with one addition:

**Validated if**, after one seasonal cycle (10-12 weeks):
- 2+ domains are actively managed through the system
- The user has used Hermes to modify plans at least 5 times (not just initial setup)
- Zero activities were missed because the system failed to re-cascade after a date slip
- The user reports that "now / next / later" in Todoist replaced manual tracking
- **Hermes's persistent memory meaningfully reduced re-explanation across planning sessions** (compared to cold-start Claude sessions)

**Killed if:**
- The user stops updating the plan store within 4 weeks and reverts to manual Todoist task management
- The Todoist task structure is too noisy or too stale to be useful
- The daily cron's condition evaluation produces wrong or unhelpful date estimates more than ~25% of the time
- The MCP-to-plan-store workflow is too slow or awkward compared to just editing Todoist directly
- **Hermes itself is too unreliable, slow, or annoying to use as the conversational interface** (model quality, gateway latency, skill invocation friction)
- **The Docker container requires more than ~30 minutes/month of maintenance** (updates, restarts, debugging)

## Build Sequence

**Week 1: Container + schema + MCP server.**
Stand up the Docker container. Configure Hermes (model provider, Telegram gateway). Build the SQLite schema. Build the MCP server with core tools (create_domain, create_activity, get_domain_plan, get_upcoming). Register it with Hermes. Write the plansync skill. Test by having a Hermes conversation plan one domain end to end.

**Week 2: Sync script + Todoist sync.**
Write daily_sync.py: weather pull, condition evaluation, trigger logic, date cascading, Todoist API sync, stdout summary. Register as a no-agent cron job. Test with the domain created in week 1.

**Week 3: Second domain + polish.**
Add a second domain via Hermes conversation. Verify cross-domain get_upcoming works. Fix whatever breaks. Add Todoist completion back-sync (API polling). Optionally add the morning briefing LLM cron job.

**Week 4+: Run it.** Use it for a full season. Resist adding features. Log what's missing and what's annoying.

## Risks

### Biggest Risk: Same as Original

The conversational-to-structured-write bridge assumes Hermes produces clean tool calls. Planning conversations are messy: the user explores options, backtracks, changes their mind. The MCP tools need to be robust to partial writes, overwrites, and false starts. The mitigation is the same: idempotent, composable tools (create, then update, rather than one-shot).

Hermes's persistent memory may partially mitigate this. If Hermes remembers that "bed 3 is the romaine bed" from three conversations ago, it needs less re-explanation and produces fewer false starts. But the skill system is what matters more: a well-written plansync skill that says "always read before write" and "use update_activity, not create+delete" will do more than memory for tool-call quality.

### Second Risk: Same as Original

Todoist expressiveness. "Watch conditions" aren't tasks. Estimated dates that shift daily cause notification fatigue. Same mitigation: limit Todoist sync to items due within 14 days.

### Third Risk: Hermes Ecosystem Maturity

Hermes Agent is ~5 months old. The cron system, MCP client, gateway, and skill system are all under active development. Breaking changes across updates are likely. The Docker deployment helps (pin the image tag, upgrade deliberately), but expect to spend time on Hermes-specific debugging that has nothing to do with the plan-sync domain logic.

Mitigation: the `plansync-data` volume is Hermes-independent. If Hermes proves too unstable, the SQLite DB, MCP server, and sync script all work with any MCP-compatible client (Claude Desktop, Claude Code, etc.) and system cron. The exit cost is low.

### Fourth Risk: Model Quality for Tool Calls

Hermes is model-agnostic. The quality of planning conversations and MCP tool calls depends heavily on which model is behind it. Claude Sonnet/Opus via API will produce better structured tool calls than a local 7B model. If using Nous Portal or OpenRouter, pin the model explicitly and test tool-call reliability before trusting it with real plans.

The no-agent cron job sidesteps this entirely: the sync logic runs deterministic Python regardless of model quality.
