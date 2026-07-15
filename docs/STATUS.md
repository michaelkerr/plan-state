# Activity Orchestrator: Project Status

> **Read this file first in every Claude Code session.**
> Update it at the end of every session.

**Last updated**: 2026-07-02
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
- [x] Domains configured: Yard (14 activities, loaded 2026-07-02) and Garden (46 activities, loaded 2026-07-15); definitions kept at domains/yard.json and domains/garden.json

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

1. **First overnight cron unverified.** The Yard domain is loaded and a manual sync run pulled real weather and evaluated conditions cleanly; the remaining Step 9 check is the autonomous 6:00/6:15 AM cron pair delivering to Telegram and the first fired trigger creating Todoist tasks (Summer Fungicide Watch is estimated to fire ~2026-07-05 after 3 days of weather history).
2. **Soil temp always NULL.** OpenWeatherMap doesn't provide soil temperature. Condition triggers using `soil_temp` metric will never fire. Authoring skill says to use daily_high as a proxy.

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

### 2026-07-15 — Second domain loaded: Garden

- Loaded the Garden domain (Murfreesboro 6-section rotation, 46 activities, 55 steps) from user-provided definition; kept at domains/garden.json for reproducibility
- Near-term first-cycle build runs 2026-07 through 2027-01; standing annual backbone (succession-system-v4) runs 2027-02 onward
- 41 calendar triggers + 5 dependency chains (potato dig ← top cut, brassica transplant ← indoor sow, garlic ← pea-vine cut, blueberry move ← bed build, fall transplants ← indoor seed); all refs verified resolved in DB
- Loaded via server._load_domain against the volume-mounted plansync.db (same file the container reads); no Todoist sync performed — the nightly cron picks up the three activities triggering today (supply order, southern peas, potato top cut)
- Grouped activities by bed identifier (group_name): S1/S2/S3/N1/N3, combos (S1+N1, S3+N3, S1+S2), and pseudo-beds Pots/Blueberry/Berries/North bed; 2027 standing-backbone activities pinned to their derived 2027 beds (Solanaceae=S3, Cucurbits=N1, Roots=N3, Alliums=S2, Legumes→Brassicas=S1); 5 cross-garden admin activities left ungrouped

### 2026-07-03 — Todoist v1 migration, duplicate-cron hardening

- First overnight cron surfaced two issues: Todoist REST v2 sunset (410 Gone on every call) and the job double-firing at 06:00 UTC + 06:00 local (stale job records predating the TZ env)
- Step 18: migrated daily_sync.py to unified API v1 (cursor-paginated projects, checked completion flag); verified live -- all 3 queued tasks created in Todoist with group prefixes
- Step 19: weather pull is now a same-local-day upsert (idempotent under duplicate runs); cron jobs deleted and recreated with local-TZ schedules; single-fire verification pending 2026-07-04 morning
- Dropped unused todoist-api-python dep whose failing import check was aborting register.sh
- Everything before Todoist worked on the first real cron: triggers fired (incl. Summer Fungicide Watch), enqueue reconciliation queued 3 items, briefing delivered with grouped bundles

### 2026-07-02 (later) — First real domain loaded: Yard

- Authored and loaded the Yard domain (North Murfreesboro lawn care, 14 activities, 5 groups) from user's detailed local-conditions brief; definition kept at domains/yard.json for reproducibility
- Manual in-container sync run: pulled real Murfreesboro weather, evaluated all 6 conditions, re-estimated Summer Fungicide Watch trigger to 2026-07-03 from forecast, zero errors
- Learned: cron evaluates condition triggers from the conditions TABLE, so condition/compound activities must include a matching conditions array; examples/fall-garden.json omits these on its compound activities (latent example bug)

### 2026-07-02 — Grouping, add_activities, Todoist fix, re-deploy

- BUILD_PLAN Steps 12, 13, 15 complete: activity group_name (bundling within domains), add_activities MCP tool (grow existing domains, refs resolve against existing activities), Todoist pending_create enqueue reconciliation (v1 gap: nothing ever queued task creation)
- Local plansync.db re-initialized fresh from updated schema (was empty)
- Re-deployed on Mac Mini: register.sh ran clean against running gideon-gateway; daily sync, MCP server, and briefing-context all verified working in-container
- Remaining for Step 9: author the first real domain, then verify overnight cron + Todoist tasks

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
