# Activity Orchestrator: Project Status

> **Read this file first in every Claude Code session.**
> Update it at the end of every session.

**Last updated**: 2026-07-01
**Current phase**: Phase 1 (Smart Notifications)
**Current migration step**: Pre-migration (v1 implemented, migration not started)

---

## Project Structure

This repo contains the **plan-state application**. Infrastructure lives in a sibling `gideon/` repo.

```
plan-state/                     # THIS REPO — application
├── register.sh                 # Installs app into running Gideon instance
├── schema.sql                  # SQLite schema (7 tables)
├── init-db.py                  # Database initializer
├── mcp-server/
│   ├── server.py               # MCP server (10 tools)
│   └── requirements.txt
├── sync/
│   ├── daily_sync.py           # 7-step deterministic sync pipeline
│   └── requirements.txt
├── scripts/                    # Cron wrappers (copied to gideon/data/scripts/ by register.sh)
│   ├── daily-sync.py
│   ├── briefing-context.py
│   └── briefing-context.sh
├── skills/                     # Hermes skills (copied to gideon/data/skills/ by register.sh)
│   ├── plansync.md
│   └── plansync-briefing.md
├── sync-output/                # Daily JSON summaries (runtime)
└── docs/

../gideon/                      # SIBLING REPO — infrastructure
├── docker-compose.yml          # Two-service Hermes deployment
├── .env                        # Secrets + PLANSYNC_PATH
└── data/                       # Hermes runtime (bind-mounted to /opt/data)
    └── config.yaml
```

**Deployment**: `cd ../gideon && docker compose up -d`, then `./register.sh`

---

## What's Built (v1)

Implemented from archive/v1-plan-sync-mvp-spec.md. Confirmed by codebase inventory 2026-06-29.

- [x] SQLite database: domains, activities, steps, conditions, weather_log, todoist_sync, activity_log tables — all 7 tables created, schema verified, WAL mode, foreign keys enabled
- [x] MCP server: get_domains, get_domain_plan, create_activity, update_activity, complete_activity, defer_activity, create_domain, add_observation, get_upcoming, get_weather_current — verified via Hermes session
- [x] Daily cron job: weather pull, condition evaluation, trigger evaluation, date cascade, overdue check, Todoist sync — runs, produces output JSON
- [x] Todoist integration: project-per-domain, task create/update/close, completion polling
- [ ] Domains configured: **NONE** — database is completely empty (0 rows in all tables)

### Codebase Inventory

| File/Module | Purpose | v1 Component | State |
|---|---|---|---|
| `schema.sql` | 7-table SQLite schema with constraints and indexes | Schema | Working |
| `init-db.py` | Database initializer | DB init | Working |
| `mcp-server/server.py` | MCP server: 10 tools over stdio JSON-RPC | MCP server | Working |
| `mcp-server/requirements.txt` | `mcp>=1.0.0` | Deps | Working |
| `sync/daily_sync.py` | 7-step deterministic sync pipeline (~650 lines) | Cron job | Working |
| `sync/requirements.txt` | `requests`, `todoist-api-python` | Deps | Working |
| `scripts/daily-sync.py` | Cron wrapper → delegates to sync/daily_sync.py | Cron entry | Working |
| `scripts/briefing-context.py` | Reads sync output + DB for LLM briefing context | Briefing data | Working |
| `scripts/briefing-context.sh` | Shell wrapper → delegates to briefing-context.py | Briefing entry | Working |
| `skills/plansync.md` | Teaches Hermes MCP tool workflow and trigger formats | Skill | Working |
| `skills/plansync-briefing.md` | Morning briefing generation instructions | Skill | Working |
| `register.sh` | Installs app into Gideon (copies skills/scripts, registers MCP + cron) | Deployment | New |

---

## Migration Progress

From docs/migration.md. Check off when verified per the verification criteria in that document.

- [ ] Step 1: New schema tables alongside existing
- [ ] Step 2: Data migration script (v1 data -> new tables)
- [ ] Step 3: MCP tools dual-read from new tables
- [ ] Step 4: Cron job writes signals alongside existing
- [ ] Step 5: Push notifications alongside Todoist
- [ ] Step 6: Resource pool tracking
- [ ] Step 7: Local LLM notification content generation
- [ ] Step 8: Domain definition YAML ingestion + authoring skill
- [ ] Step 9: System health + external watchdog
- [ ] Step 10: Old tables retired
- [ ] Step 11: (Optional) Cron -> processing loop

---

## In Progress

_Nothing yet. Migration not started._

---

## Known Issues / Blockers

1. **Database is empty.** All v1 code works but has never processed real data. No domains, activities, or weather history exist.
2. **Soil temp always NULL.** OpenWeatherMap doesn't provide soil temperature. Condition triggers using `soil_temp` metric will never fire.
3. **Re-deploy needed.** Project was split from a monorepo into plan-state + gideon. Mac Mini needs the new two-repo layout deployed.

---

## Decisions Made (Post-PRD)

### 2026-07-01 — Project split: plan-state + gideon

Separated infrastructure (Gideon: Docker compose, Hermes config, security) from application (plan-state: schema, MCP server, sync pipeline, skills). Gideon can be upgraded independently. Plan-state registers itself into Gideon via register.sh.

### 2026-06-29 — Empty DB simplifies migration sequence

The database has zero data. Migration Step 2 (data migration script) can be a skeleton rather than a blocker.

### 2026-06-29 — Consider reordering migration steps

With no existing data to protect, Step 8 (YAML ingestion) could move earlier.

---

## Next Session: What To Do

1. Read this file (STATUS.md).
2. Deploy the two-repo layout on the Mac Mini (see register.sh).
3. Create the first domain via Hermes MCP tools to validate end-to-end.
4. Update this file before ending the session.

---

## Document Map

| Document | What it is | When to update |
|---|---|---|
| **STATUS.md** (this) | Current state, session entry point | Every session |
| **prd.md** | Target architecture + requirements | When requirements change |
| **archive/v1-plan-sync-mvp-spec.md** | Original v1 spec (as-built) | Never (frozen) |

---

## Session Log

Newest first.

### 2026-07-01 — Project separation

- Split monorepo into two: `gideon/` (infrastructure) and `plan-state/` (application)
- Gideon repo: docker-compose.yml, .env.example, config.yaml, security docs
- Plan-state repo: schema, MCP server, sync pipeline, skills, scripts, register.sh
- register.sh replaces setup.sh — copies skills/scripts to gideon/data/, registers MCP + cron
- Container paths unchanged (/opt/data, /opt/plansync)
- Next: deploy new layout on Mac Mini, create first domain

### 2026-06-29 — Codebase inventory and reconciliation

- Inventoried every project file, read all source code
- Confirmed all v1 components are implemented and working
- Discovered database is completely empty
- Updated STATUS.md with full inventory

### 2026-06-29 — Project setup

- Created docs/ folder structure, PRD, implementation doc, migration doc
