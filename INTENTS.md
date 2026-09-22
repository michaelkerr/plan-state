# Dispatch + Plan-State: Design Intent

## Core product insight

Domain knowledge about what to do and when — gardening schedules, lawn
treatment windows, hunting season prep, home maintenance intervals — dies
in chat transcripts, scattered notes, and the user's head.  Calendars
cannot express conditional triggers ("when soil hits 55 °F for 3 days").
Task managers cannot cascade prep windows or react to weather.

What is missing is a **persistent runtime** that monitors conditions,
manages preparation timelines, and pushes the right action at the right
time.  The value comes from the combination of structured plans and
condition-aware execution — neither alone is enough.

## Two-layer model

The system is split into two distinct concerns that ship together in one
repository as two packages.

### dispatch — condition-aware execution engine

The only running service.  A pure execution engine with no domain
knowledge and no opinion about gardens or hunting.

Responsibilities:
- Store items with triggers in SQLite (single source of truth)
- Evaluate weather conditions hourly via OpenWeatherMap
- Fire triggers (calendar, condition, dependency, compound)
- Generate briefings and nudges from live DB state
- Handle completions with deterministic name/code resolution
- Expose a small MCP tool surface (target: 6 tools)
- Provide a CLI for eval, briefing, nudge, doctor

dispatch never reads cached markdown, daily JSON, or dossiers for
decisions.  Everything comes from the DB at call time.

### plan-state — plan quality framework

A CLI/library plus Hermes skills.  Not a server.  Ensures the plan
feeding dispatch is correct, current, and complete.

Responsibilities:
- Define a generic domain context schema (entities, states, params)
- Guide authoring conversations that produce validated domain contexts
- Instantiate paths (templates) into dispatch items
- Reconcile dispatch state against domain context to detect drift
- Guide season turnover (what changed, what is next, updated context)
- Adapt to the user's knowledge base (Obsidian, config YAML, etc.)

plan-state is not prescriptive about where domain knowledge lives.  It
is prescriptive about the **handoff format** — what dispatch receives.

### Event bridge

dispatch appends structured events to an append-only log.  plan-state
reads the log on demand (via cron or manual invocation).  Hermes is the
glue for MVP: cron triggers dispatch eval, skills invoke plan-state
reconcile.  No webhooks, no message queue — a file and a cron.

## Vocabulary

| Term              | Definition                                                                |
|-------------------|---------------------------------------------------------------------------|
| **Item**          | One actionable unit: `watching` → `due` → `done` / `skipped`             |
| **Trigger**       | Condition that moves an Item to `due`: calendar, condition, after, compound|
| **Checklist**     | Optional soft sub-bullets on an Item (no separate state machine)          |
| **Path**          | Versioned YAML template that instantiates Items for a season/project      |
| **Event**         | Append-only log entry: fires, completes, defers, weather snapshots        |
| **Domain context**| Structured description of a domain: entities, current states, params      |
| **Reconcile**     | Compare dispatch items against domain context; flag drift                 |
| **Season turnover**| Guided review: what happened, what changed, what comes next              |
| **KB adapter**    | Pluggable reader/writer for a knowledge base (Obsidian, YAML, etc.)      |

## Non-goals

- **Lifecycle state machine (now).**  Automatic lifecycle advancement and
  transition guards are a planned future destination, not a current build.
  For now, lifecycle state is manual/conversational.
- **Prescriptive knowledge base.**  dispatch and plan-state do not require
  Obsidian, Notion, or any specific note system.  The handoff format is
  the contract; how parameters get filled is the user's business.
- **Recurrence engine.**  Annual plans are re-authored each season via
  path instantiation.  No cron-level recurrence on items.
- **Multi-user.**  Single operator, single writer.  Multi-user is out of
  scope until the single-user path is proven.
- **Domain-specific logic in shared code.**  No `if domain == "garden"`
  anywhere.  Garden, hunting, and lawn are example paths, not product
  identity.
- **Replacing Hermes.**  dispatch is a capability that registers into
  Hermes (or any MCP client).  It does not replace the agent, the chat,
  or the delivery surface.

## Planned destination: general-purpose lifecycle engine

product-delivery (software delivery workflows) and plan-state (life
domain management) are the same structural pattern:

- A state machine managing lifecycles
- Transition guards gated on evidence or conditions
- Execution delegated to external tools that report back
- Events that advance state

We plan to extract a shared lifecycle kernel after running both systems
for a real season.  This shapes current design decisions:

- All schemas are entity-agnostic (no `bed_id`, no `crop_family` in
  shared code)
- The event log carries enough context for a future engine to replay
  and reconstruct state (`domain`, `source_ref`, `event_type`,
  `timestamp`, `payload`)
- The handoff format uses opaque `source_ref` back to plan-state,
  not domain-specific identifiers
- Paths declare parameter schemas so a future lifecycle engine can
  validate them against an ontology
- Reconcile works against the generic context schema

### Promotion criteria

Promote the lifecycle engine from Later to Now if, after one season:

- Manual rotation/turnover happens more than 3-4 times per season and
  errors occur
- product-delivery's state machine and plan-state's domain context
  feel like the same thing in different vocabulary

## Distribution

**Now: Hermes-first.**  Ship as a Portable Agent Plugins v1 package.
Install via `hermes plugins install`, enable, configure env, set up
cron.  Friends with Hermes can use it.

**Roadmap: Both.**  Same dispatch kernel as `uvx dispatch mcp` for
Claude Desktop / Cursor.  Hermes plugin becomes a thin wrapper
distributing skills and cron templates over the kernel.
