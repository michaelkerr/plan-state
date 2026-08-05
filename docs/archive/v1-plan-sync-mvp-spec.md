# Plan-State Synchronizer: MVP Spec (As Built)

> Archived from the original spec. Updated 2026-06-28 to reflect what was actually deployed.

## What This Is

A three-part system that turns LLM-generated domain plans into managed, condition-aware Todoist tasks that re-cascade automatically when things slip, complete, or change.

**Conversational layer:** Hermes Agent (branded externally as "Brodie") running in Docker on a Mac Mini home server. Connects to Telegram via outbound long polling. Reads and writes structured plans to a SQLite store via a local MCP server.
**Middle:** SQLite database holds canonical plan state: activities, conditions, prep chains, dependencies, status, history.
**Downstream:** A no-agent cron job (deterministic Python, zero LLM involvement) pulls weather/conditions, evaluates triggers, re-cascades dates, and syncs the result to Todoist. An optional LLM cron job generates a morning briefing from the sync output.

## What Changed from the Original Spec

| Original Spec | As Built |
|---|---|
| Claude sessions + custom MCP server | Hermes Agent + same MCP server (Hermes as MCP client) |
| System cron at 6 AM | Hermes no-agent cron (deterministic script, zero tokens) |
| No notification system (Todoist only) | Hermes gateway delivers briefings to Telegram |
| No persistent conversational memory | Hermes cross-session memory + skill system |
| Three separate processes to manage | One Docker container (gateway + dashboard) |
| Cloud API assumed (Anthropic) | Local Qwen3 14B via Ollama on a separate LAN machine |
| Public DNS + Caddy TLS | Tailscale-only access, no public exposure |
| HTTP healthcheck on port 8642 | Process-based healthcheck (gateway doesn't expose HTTP) |
| External naming: "hermes" | External naming: "brodie" (subdomains, containers) |

## What This Tests

1. Does a structured plan store that Hermes can read/write eliminate the "plan dies in the chat transcript" problem?
2. Does daily condition checking + automatic date cascading solve the "right thing, wrong time" and "missed the prep window" failures?
3. Is Todoist a sufficient interaction surface for "now / next / later" across multiple domains?
4. Does Hermes's persistent memory + skill system reduce the friction of planning conversations compared to cold-start Claude sessions?

## Core User Flow

1. User messages Brodie via Telegram.
2. User says: "Help me plan my fall garden succession for Zone 7a, beds 2 and 3, starting late August."
3. Hermes generates the plan AND writes it to the plan store via the plan-sync MCP tools. Activities, trigger conditions, prep steps with lead times, follow-up steps, dependencies.
4. Every morning at 6 AM Central, the no-agent cron job runs the sync script:
   - Pulls weather (current + 7-day forecast) for each location
   - Evaluates every "watching" activity's trigger conditions against current data
   - When a trigger fires: marks the activity "active," cascades prep step dates backward from trigger date
   - When a trigger date estimate shifts: re-cascades all dependent dates
   - When an activity or step is completed: cascades forward to follow-up steps and dependent activities
   - Syncs the result to Todoist: creates/updates/completes tasks, adjusts due dates, writes contextual descriptions
   - Writes a structured summary to stdout (delivered to Telegram if non-empty)
5. At 6:15 AM, an LLM cron job reads today's sync output and generates a human-readable morning briefing, delivered to Telegram.
6. User sees updated tasks in Todoist throughout the day. Completes them there (next-morning API poll syncs completions back to the plan store).
7. When something changes, user messages Brodie on Telegram, discusses it, Hermes updates the plan store via MCP, next cron run re-cascades and re-syncs.

## Deployment: As Built

### Architecture

Single Docker container (`nousresearch/hermes-agent:v2026.6.19`) running on a Mac Mini home server. Two compose services share the same image:

- **brodie-gateway** — runs `gateway run`, handles Telegram, MCP server subprocess, cron jobs
- **brodie-dashboard** — runs `dashboard`, read-only view of sessions and memory

Access is Tailscale-only. No public DNS, no Caddy, no ports open to the internet. The gateway connects outbound to Telegram's API (long polling) — nothing inbound is required.

### docker-compose.yml (actual)

```yaml
services:
  gateway:
    image: nousresearch/hermes-agent:${HERMES_VERSION}
    container_name: brodie-gateway
    restart: unless-stopped
    command: gateway run
    env_file: .env
    volumes:
      - ./brodie-data:/opt/data
      - ./plansync-data:/opt/plansync
    healthcheck:
      test: ["CMD", "pgrep", "-f", "hermes"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2.0"
          pids: 256
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - DAC_OVERRIDE
      - CHOWN
      - FOWNER
      - SETUID
      - SETGID

  dashboard:
    image: nousresearch/hermes-agent:${HERMES_VERSION}
    container_name: brodie-dashboard
    restart: unless-stopped
    command: dashboard
    ports:
      - "${DASHBOARD_BIND}:9119:9119"
    depends_on:
      gateway:
        condition: service_healthy
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - SETUID
      - SETGID
```

### Deployment Discoveries

Things the spec got wrong or didn't anticipate:

1. **Image tags are date-based** (`v2026.6.19`), not semver (`v0.6.0`).
2. **Gateway does not expose an HTTP endpoint.** The original spec assumed port 8642 had a `/health` endpoint. It doesn't — the gateway only polls Telegram outbound. Healthcheck switched to `pgrep`.
3. **`cap_drop: ALL` is too aggressive.** The s6 init system inside the container needs `SETUID` and `SETGID` to drop privileges via `s6-applyuidgid`. Both gateway and dashboard need these.
4. **`pids_limit` conflicts with `deploy.resources.limits.pids`.** Newer Docker Compose treats them as the same field and errors if both are set. Use only `deploy.resources.limits.pids`.
5. **No `pip` in the container.** The Hermes image uses a venv at `/opt/hermes/.venv/`. Install packages via `python3 -m ensurepip` then `python3 -m pip install`. The `mcp` and `requests` packages are pre-installed; only `todoist-api-python` needed manual installation.
6. **No `sqlite3` CLI in the container.** The briefing-context script was rewritten from bash (using `sqlite3 -json`) to Python (using the built-in `sqlite3` module).
7. **Ollama context window defaults are too small.** Hermes requires 64K minimum context. Ollama reports 40,960 for Qwen3 14B by default. Required `model.context_length: 131072` and `model.ollama_num_ctx: 65536` overrides in Hermes config.
8. **First model load is slow (~2 minutes).** Subsequent calls are fast while the model stays resident. Use `OLLAMA_KEEP_ALIVE=-1` on the Ollama server to prevent unloading.
9. **Hermes setup wizard overwrites config.yaml.** Run the wizard first, then verify security hardening settings are still present.
10. **macOS .env editing.** Files named `.env` can't be edited in some macOS editors. Rename to `.env.txt`, edit, rename back.

### Model: Local Qwen3 14B

Running on a separate MacBook Pro M1 (32GB) via Ollama at `http://10.0.0.14:11434/v1`.

- Qwen3 72B doesn't fit (needs ~42GB at Q4)
- Qwen3 14B at Q4 uses ~9GB, fits comfortably
- Context window overridden to 65536 tokens (Hermes minimum 64K)
- Configured via `hermes setup model` → OpenAI-compatible endpoint

### Volume Layout (actual)

```
./brodie-data/                    # mounted at /opt/data
  config.yaml                     # Hermes config (generated by setup wizard + hardened)
  .env                            # provider keys (written by setup wizard)
  skills/
    plansync.md                   # plan-sync skill
    plansync-briefing.md          # morning briefing skill
  scripts/
    daily-sync.py                 # cron wrapper → delegates to /opt/plansync/sync/
    briefing-context.sh           # shell wrapper → delegates to briefing-context.py
    briefing-context.py           # reads sync output + DB, outputs context for LLM
  cron/                           # managed by Hermes
  memory/                         # persistent memory store
  sessions/                       # conversation history

./plansync-data/                  # mounted at /opt/plansync
  plansync.db                     # SQLite database (canonical plan state)
  schema.sql                      # schema definition
  init-db.py                      # database initializer
  mcp-server/
    server.py                     # MCP server (10 tools)
    requirements.txt              # mcp>=1.0.0
  sync/
    daily_sync.py                 # deterministic sync: weather → conditions → Todoist
    requirements.txt              # requests, todoist-api-python
  sync-output/                    # daily JSON summaries
```

The split between `brodie-data` and `plansync-data` is intentional. Hermes image upgrades should never risk the plan database or custom scripts. The plan store is Hermes-independent.

## Components

### 1. SQLite Schema

Seven tables with constraints and indexes. Implemented in `plansync-data/schema.sql`.

```
domains          — planning domains (Fall Garden, Lawn Care, etc.)
activities       — things to do, with trigger definitions and status
steps            — prep and follow-up steps with lead_days offsets
conditions       — weather/calendar conditions to evaluate
weather_log      — daily weather snapshots per location
todoist_sync     — mapping between plan items and Todoist tasks
activity_log     — audit trail of all changes with source attribution
```

Key constraints enforced in schema:
- `activities.status` CHECK constraint: watching | preparing | active | completed | skipped | deferred
- `steps.step_type` CHECK: prep | follow_up
- `conditions.condition_type` CHECK: temperature | weather_event | calendar | dependency
- `activity_log.source` CHECK: cron | hermes | todoist_webhook
- Foreign keys enabled via `PRAGMA foreign_keys=ON`
- WAL journal mode for concurrent read safety

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

### 2. MCP Server (Python, stdio)

Implemented in `plansync-data/mcp-server/server.py`. Uses the `mcp` Python SDK. Runs as a child process of Hermes, communicates over stdin/stdout JSON-RPC.

Registered in Hermes config and via CLI:
```bash
hermes mcp add plansync --command python3 --args "/opt/plansync/mcp-server/server.py" --env PLANSYNC_DB=/opt/plansync/plansync.db
```

**10 tools implemented:**

- `get_domains()` — list all domains with activity counts by status
- `get_domain_plan(domain_id)` — full plan with activities, steps, conditions
- `create_domain(name, location, notes)` — new domain
- `create_activity(domain_id, name, description, trigger_type, trigger_def, steps[], conditions[])` — create activity with steps and conditions, auto-computes dates for calendar triggers
- `update_activity(activity_id, ...)` — modify fields, re-cascades on trigger_date change
- `complete_activity(activity_id, notes?)` — marks complete, cascades follow-ups, activates dependent activities
- `defer_activity(activity_id, new_date?, reason?)` — defers and re-cascades
- `add_observation(domain_id, observation_text, affects_activities[]?)` — records observation in activity_log
- `get_upcoming(days_ahead=14)` — cross-domain view with overdue detection
- `get_weather_current(location)` — latest weather + 7-day history

**What the MCP server does NOT do:** condition evaluation, Todoist sync. Those are the cron job's responsibility. Exception: explicit date changes cascade steps immediately so the user sees updated plans in-conversation.

### 3. Daily Cron Job (No-Agent Mode)

Implemented in `plansync-data/sync/daily_sync.py`. Registered as a Hermes no-agent cron job:

```bash
hermes cron create "0 6 * * *" --no-agent --script daily-sync.py --deliver telegram --name "plan-sync"
```

**7-step pipeline:**

1. **Weather pull** — OpenWeatherMap current + 5-day/3-hour forecast per location
2. **Condition evaluation** — temperature, weather event, calendar, dependency checks against weather_log
3. **Trigger evaluation** — fires triggers for watching activities, handles calendar/condition/dependency/compound types
4. **Date re-cascade** — re-estimates condition-based trigger dates from forecast data, cascades step dates
5. **Overdue check** — flags past-due steps
6. **Todoist sync** — create/update/close tasks, poll for Todoist-side completions
7. **Summary output** — structured stdout (delivered to Telegram if non-empty), JSON saved to sync-output/

### 4. Morning Briefing (LLM Cron Job)

Registered at 6:15 AM, 15 minutes after the sync:

```bash
hermes cron create "15 6 * * *" --script briefing-context.sh --deliver telegram --skill plansync-briefing --name "morning-briefing"
```

The `briefing-context.sh` wrapper calls `briefing-context.py`, which reads today's sync output JSON and queries the DB for upcoming activities, due steps, and recent weather. Its stdout becomes context for the `plansync-briefing` skill, which instructs the LLM to produce a concise morning summary.

### 5. Hermes Skills

Two skill documents in `brodie-data/skills/`:

- **plansync.md** — teaches Hermes the MCP tool workflow, trigger type formats, and guardrails ("always read before write," "don't evaluate conditions yourself")
- **plansync-briefing.md** — instructions for generating the morning briefing (format, tone, length target of 100-200 words)

### 6. Todoist Structure

Unchanged from original spec. One project per domain, sections per activity group, tasks per step.

## What NOT to Build

Everything from the original spec, plus:
- **Custom notification delivery.** Hermes gateway handles this natively.
- **Hermes skills for condition evaluation.** The sync script handles this deterministically.
- **Multi-container orchestration.** One container, one process tree.
- **Custom dashboard.** Hermes built-in dashboard; Todoist is the primary UI.
- **Webhook receiver.** Todoist completion sync via API polling.
- **Public DNS / Caddy / TLS.** Tailscale-only access.

## Success / Failure Criteria

**Validated if**, after one seasonal cycle (10-12 weeks):
- 2+ domains are actively managed through the system
- The user has used Hermes to modify plans at least 5 times (not just initial setup)
- Zero activities were missed because the system failed to re-cascade after a date slip
- The user reports that "now / next / later" in Todoist replaced manual tracking
- Hermes's persistent memory meaningfully reduced re-explanation across planning sessions

**Killed if:**
- The user stops updating the plan store within 4 weeks and reverts to manual Todoist task management
- The Todoist task structure is too noisy or too stale to be useful
- The daily cron's condition evaluation produces wrong or unhelpful date estimates more than ~25% of the time
- The MCP-to-plan-store workflow is too slow or awkward compared to just editing Todoist directly
- Hermes itself is too unreliable, slow, or annoying to use as the conversational interface
- The Docker container requires more than ~30 minutes/month of maintenance

## Risks (Updated with Deployment Experience)

### Local Model Quality

The system runs on Qwen3 14B, which is substantially smaller than the Claude Sonnet/Opus models the original spec assumed. MCP tool call quality and planning conversation coherence may be limited. The no-agent cron job sidesteps this — sync logic runs deterministic Python regardless of model quality. If tool calls prove unreliable, the first option is upgrading to a larger local model (Qwen3 30B-A3B fits in 32GB) or switching to a cloud API for planning conversations only.

### Todoist Expressiveness

Same as original spec. "Watch conditions" aren't tasks. Shifting dates cause notification fatigue. Mitigation: limit Todoist sync to items due within 14 days.

### Hermes Ecosystem Maturity

Confirmed during deployment. The image tag format, config.yaml structure, capability requirements, and available CLI tools all required discovery. The Docker deployment helps (pin the image tag, upgrade deliberately), but expect container-specific debugging.

### Model Load Time

Cold-loading Qwen3 14B with 64K context takes ~2 minutes on the M1. Subsequent calls are fast while resident. For Telegram interactions, this means the first message after an idle period will be slow. `OLLAMA_KEEP_ALIVE=-1` mitigates but requires Ollama to stay running.

## Build Sequence (Actual)

**Session 1:** Built all code — Docker compose (security-hardened), SQLite schema, MCP server (10 tools), daily sync script (7-step pipeline), Hermes skills, cron scripts, briefing system, setup automation.

**Session 2:** Deployed to Mac Mini. Fixed image tag format, capability issues (SETUID/SETGID), pids_limit conflict, healthcheck (no HTTP endpoint), pip path, sqlite3 CLI missing, Ollama context window defaults. Configured local Qwen3 14B via Ollama. Registered cron jobs. Verified MCP tools respond. Dashboard operational.

**Next:** Create first domain via Telegram conversation. Validate end-to-end flow through one daily sync cycle. Add second domain. Run for a season.
