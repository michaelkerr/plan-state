# Activity Orchestrator: Project Status

> **Read this file first in every Claude Code session.**
> Update it at the end of every session.

**Last updated**: 2026-06-29
**Current phase**: Phase 1 (Smart Notifications)
**Current migration step**: Pre-migration (v1 implemented, migration not started)

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
| `docker-compose.yml` | Two-service Docker deployment (gateway + dashboard), security-hardened | Deployment | Working |
| `.env` | Live secrets/config | Deployment | Working |
| `.env.example` | Template for .env | Docs | Stale (HERMES_VERSION=v0.6.0, should be date-based) |
| `Caddyfile` | Reverse proxy for public HTTPS | Not in v1-as-built | Unused (Tailscale-only) |
| `SECURITY-CHECKLIST.md` | 18-item security checklist | Ops docs | Stale (item 2 references port 8642) |
| `setup.sh` | Post-boot: DB init, pip install, MCP + cron registration | Deployment | Working |
| `plan-sync-mvp-spec-hermes.md` | Original input spec | Historical | Superseded by docs/archive/ |
| `plansync-data/schema.sql` | 7-table SQLite schema with constraints and indexes | Schema | Working |
| `plansync-data/init-db.py` | Database initializer | DB init | Working |
| `plansync-data/plansync.db` | Live SQLite database | Data store | Working, empty |
| `plansync-data/mcp-server/server.py` | MCP server: 10 tools over stdio JSON-RPC | MCP server | Working |
| `plansync-data/mcp-server/requirements.txt` | `mcp>=1.0.0` | Deps | Working |
| `plansync-data/sync/daily_sync.py` | 7-step deterministic sync pipeline (~650 lines) | Cron job | Working |
| `plansync-data/sync/requirements.txt` | `requests`, `todoist-api-python` | Deps | Working |
| `plansync-data/sync-output/` | Daily JSON summaries | Output | Working (empty output) |
| `gideon-data/config.yaml` | Hermes config: model, MCP, security, cron | Config | Working |
| `gideon-data/scripts/daily-sync.py` | Cron wrapper → delegates to sync/daily_sync.py | Cron entry | Working |
| `gideon-data/scripts/briefing-context.sh` | Shell wrapper → delegates to briefing-context.py | Briefing entry | Working |
| `gideon-data/scripts/briefing-context.py` | Reads sync output + DB for LLM briefing context | Briefing data | Working |
| `gideon-data/skills/plansync.md` | Teaches Hermes MCP tool workflow and trigger formats | Skill | Working |
| `gideon-data/skills/plansync-briefing.md` | Morning briefing generation instructions | Skill | Working |

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

1. **Database is empty.** All v1 code works but has never processed real data. No domains, activities, or weather history exist. Data migration script (Step 2) will be a no-op initially.
2. **Soil temp always NULL.** OpenWeatherMap doesn't provide soil temperature. Condition triggers using `soil_temp` metric will never fire. Need a different signal source or manual entry.
3. **`.env.example` stale.** Shows `HERMES_VERSION=v0.6.0` but actual image tags are date-based (`v2026.6.19`).
4. **SECURITY-CHECKLIST.md stale.** Item 2 says "Gateway port 8642 bound to 127.0.0.1" but gateway has no port mapping.

---

## Decisions Made (Post-PRD)

Decisions made during implementation that aren't in prd.md's Design Decisions Log. Date and rationale.

### 2026-06-29 — Empty DB simplifies migration sequence

The database has zero data. Migration Step 2 (data migration script) can be a skeleton rather than a blocker. Real testing happens after the first domain is created via MCP tools or YAML ingestion.

### 2026-06-29 — Consider reordering migration steps

With no existing data to protect, Step 8 (YAML ingestion) could move earlier to enable efficient initial domain setup. Step 5 (push notifications) should wait until at least one domain has been validated end-to-end through a trigger cycle.

---

## Next Session: What To Do

1. Read this file (STATUS.md).
2. Begin Migration Step 1: add the new schema tables from docs/implementation.md to the existing SQLite database. Do not modify or drop existing tables.
3. Verify: existing cron job and MCP tools still work after new tables are added.
4. Create the first domain via Hermes MCP tools to validate the existing v1 pipeline end-to-end before migrating further.
5. Update this file before ending the session.

---

## Document Map

| Document | What it is | When to update |
|---|---|---|
| **STATUS.md** (this) | Current state, session entry point | Every session |
| **prd.md** | Target architecture + requirements | When requirements change |
| **implementation.md** | Schema, skills, build patterns | When schema or skills change |
| **migration.md** | Step-by-step v1 -> target | Check off completed steps |
| **archive/v1-plan-sync-mvp-spec.md** | Original v1 spec (as-built) | Never (frozen) |

---

## Session Log

Newest first. Brief summary of what was accomplished.

### 2026-06-29 — Codebase inventory and reconciliation

- Read all target architecture docs (PRD, implementation, migration, BOOTSTRAP)
- Inventoried every project file, read all source code
- Confirmed all v1 components are implemented and working
- Discovered database is completely empty (no domains created yet)
- Identified 4 known issues (empty DB, soil temp, stale docs)
- Produced three-list reconciliation (implemented / missing / extra)
- Proposed migration plan adjustments based on empty-DB reality
- Updated this STATUS.md with full inventory and findings
- Next: Migration Step 1 (new schema tables) or create first domain

### 2026-06-29 — Project setup

- Created docs/ folder structure
- Finalized PRD with Design Decisions Log (10 decisions captured)
- Created implementation doc (schema, 3 skills with examples, build sequence)
- Created migration doc (11 steps from v1 to target)
- Created this STATUS.md
- Next: codebase inventory and Migration Step 1
