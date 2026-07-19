# Activity Orchestrator PRD

## Problem Statement

Many life domains (gardening, lawn care, hunting, health optimization, home maintenance, etc.) involve recurring activities governed by complex timing logic: seasonal windows, environmental conditions, regulatory calendars, dependency chains, and preparation sequences. No single existing tool category handles this well:

- Calendar apps handle fixed dates but cannot express conditional triggers ("when soil temp hits 55°F for 3 consecutive days").
- Task/project management tools handle dependencies and checklists but lack condition monitoring, lead-time cascading, and cyclical recurrence.
- Reminder apps are stateless and one-dimensional.
- Domain-specific apps (garden planners, hunting season trackers) are siloed and non-extensible.

The result: domain knowledge about what to do and when lives in the user's head (or scattered across notes, articles, and experience), and the user must manually translate that knowledge into calendar events, reminders, and mental checklists each season. This is error-prone, high-overhead, and fails to adapt when conditions change.

LLMs can encode this domain knowledge and express it as structured configuration. What is missing is a persistent runtime that accepts those definitions, monitors conditions, manages preparation timelines, and delivers actionable notifications at the right time.

### Core Product Insight

The differentiating value of this system is **LLM-contextual proactive notifications for condition-dependent activities**. A traditional system says "soil temp hit 55°F, apply pre-emergent." This system says "soil temp hit 55°F this morning, but there's rain forecast Thursday. Apply Wednesday. You have 4 lbs of Barricade, enough for your 8,000 sqft. Also: your overseeding window opens in 6 weeks, so coordinate timing." The LLM's ability to synthesize across current conditions, domain state, and cross-domain context at notification time is the reason this system exists.

### Operating Context: Single-Operator Personal System

This system is designed for a single user who is also the sole operator. There is no ops team, no SRE on call, no one watching dashboards. If the system breaks while the user is in a tree stand or spreading pre-emergent, it stays broken until the user returns and notices. Every architectural and operational decision must account for this constraint. Complexity that requires active monitoring or manual intervention to keep running is a liability, not a feature.

## Launch Scope and Phasing

The full architecture described in this PRD is the target state. Launch scope is deliberately constrained to validate the core product insight before enabling self-modification capabilities. The signal/boundary infrastructure is built fully at launch because it is the foundation, and building a simpler pipeline now means rebuilding later. What is constrained is the surface area of agent capabilities.

### Launch (Phase 1): Smart Notifications

**In scope:**
- Full signal/boundary infrastructure: signal space with durable persistence, tag-based routing, boundary enforcement, crash recovery.
- 2-3 domain agents, pre-authored by the user (with LLM assistance during authoring sessions), not dynamically created by the orchestrator at runtime. Candidates: lawn care, garden, hunting.
- Activity agents with full trigger evaluation (calendar, signal-based, dependency, compound), prep/follow-up chains, and lifecycle management. All rule-based.
- Condition monitor agents for environmental triggers. Rule-based or ML-backed as appropriate.
- Resource pool agent with inventory tracking, demand/conflict detection.
- Notification delivery agent with push notifications (mobile push or SMS).
- Orchestrator agent scoped to: notification content generation (FR-7.1) and interactive state querying via conversational interface (FR-13.2). The orchestrator reads domain state and generates contextual notifications. It does not modify agent configurations, propose adaptations, or alter boundaries.
- LLM reasoning backing: local model for notification content generation (low-latency, zero marginal cost, no external dependency). Cloud API for interactive orchestrator sessions (authoring, querying, complex reasoning).
- Signal source adapters for weather and calendar data.
- System health monitoring with external watchdog (FR-15.2).
- Signal source quality monitoring (FR-14).
- Data collection for future adaptation: trigger accuracy history, signal absorption metrics, activity outcomes. Collected but not acted on autonomously.
- Interaction surfaces: push notifications (mandatory), conversational interface to orchestrator (for authoring and querying), simple dashboard/timeline view.

**Deferred to Phase 2: Adaptation and Evolution**
- FR-8 (Adaptation and Evolution) in its entirety. No autonomous adaptation proposals, no boundary evolution, no structural agent changes. Trigger thresholds, boundaries, and configurations are manually tuned by the user based on first-season experience and collected data.
- Dynamic agent creation by the orchestrator. All agents in Phase 1 are pre-authored.
- Agent structural changes (splitting, merging, spawning).
- Cold review mechanism (FR-8.7). Deferred because there are no autonomous adaptations to review.

**Deferred to Phase 3: Self-Modification and Scaling**
- Full orchestrator capabilities: autonomous configuration authoring, adaptation proposals, boundary evolution, structural changes.
- Agent templates and parameterized instantiation.
- Multiple orchestrator agents with distinct specializations.
- Additional interaction surfaces beyond the core three.
- Multi-user support (Open Question #2).
- Agent marketplace / sharing (Open Question #3).

### Phase Gate Criteria

**Phase 1 -> Phase 2**: The system has operated for at least one full season (or equivalent cycle for non-seasonal domains). Trigger accuracy data exists for all activity agents. The user has manually adjusted at least 3 configurations based on observed outcomes, validating that the collected data supports tuning decisions. The notification content generation has proven its value: the user can articulate specific instances where the LLM-contextual notification changed their behavior vs. what a static reminder would have produced.

**Phase 2 -> Phase 3**: The adaptation mechanism has proposed at least 10 changes. The user has accepted and rejected proposals with enough history to validate that the meta-adaptation calibration (FR-8.6) is producing useful proposals, not noise. No critical failures have occurred from accepted adaptations.

## Architectural Model: Signals and Boundaries

This system is modeled as a complex adaptive system following the framework in John Holland's *Signals and Boundaries*. The architecture is federated, not monolithic. There is no central coordinator. Autonomous agents interact through tagged signals flowing across semi-permeable boundaries, and system-level behavior (cross-domain coordination, resource conflict detection, unified scheduling) emerges from those local interactions.

### Why This Model

The domains this system covers have nothing in common structurally. Forcing them into a shared schema means either the schema is so generic it encodes nothing useful, or so complex that configuration becomes the bottleneck. Holland's framework solves this: each domain is an autonomous agent with its own internal model, its own signal processing rules, and a boundary that determines what information crosses in and out. The common infrastructure is the signal medium, not a domain-aware coordinator.

Critically, the signal/boundary infrastructure is not exotic. It is a formalized event-driven architecture with topic-based routing. A signal is an event. A boundary is a subscription filter. An agent is a stateful event processor. The Holland framing provides the conceptual model; the implementation is a durable event store with tag-based matching. The infrastructure cost is mostly one-time and is not dramatically more than a well-designed event pipeline without the formalization.

### Fractal Agent Principle

The system applies a single organizational primitive at every level of scale: the agent with a boundary and an internal model, interacting through tagged signals. This principle is applied fractally:

- A **step agent** (finest grain) tracks completion of a single prep or follow-up action, absorbing signals from its parent activity and emitting lifecycle signals on completion.
- An **activity agent** contains step agents, manages its own trigger evaluation and lifecycle, absorbs signals filtered by its parent domain agent's boundary.
- A **domain agent** contains activity agents, maintains a domain-specific internal model, defines the outermost boundary for its domain's signal subscriptions and emissions.
- An **orchestrator agent** reasons across domains, proposes adaptations (Phase 2+), generates dynamic content, and interacts with the system exclusively through signal exchange governed by its own boundary.
- **Infrastructure agents** (notification delivery, resource pool, aggregation) provide shared services, each with their own boundaries and signal processing rules.
- The **user** is conceptually an agent: they have a boundary (notification preferences, attention capacity), they emit signals (completions, annotations, observations, overrides), and they maintain an internal model the system cannot directly observe but which drives their decisions.

No entity in the system has privileged access in the production signal-exchange layer. Every agent-to-agent interaction occurs through the same signal/boundary mechanism. Administrative and debugging access to agent state exists outside this layer (see NFR-10).

### Agents and Reasoning Backing

An agent is defined by its boundary, internal model, and signal processing contract. It is explicitly *not* defined by what reasoning capability backs its signal processing. The reasoning backing is a configuration detail, not an identity.

The spectrum of reasoning backings:

- **Rule-based / scripted**: Simple threshold checks, state machines, event-driven logic. A condition monitor that emits a signal when soil temp exceeds 55°F for 3 consecutive readings. A step agent that tracks completion state. Low cost, deterministic, sufficient for the majority of agents in the system.
- **ML model**: Trained models for pattern recognition or probabilistic assessment. A frost risk monitor that interprets multiple weather signal types and emits a probabilistic risk signal. More capable than rules, still specialized and relatively inexpensive.
- **Local LLM**: A locally-hosted language model (e.g., quantized open-source model running on user's hardware). Zero marginal cost per invocation, no external API dependency, no latency to remote services. Suitable for constrained reasoning tasks: notification content generation, qualitative state summarization, signal interpretation. The primary reasoning backing for agents that need LLM capabilities in the automated pipeline (notification content generation in FR-7.1).
- **Cloud LLM**: Full-capability cloud-hosted model (Claude, GPT, etc.). The most capable backing, used for tasks requiring frontier reasoning: interactive orchestrator sessions, complex cross-domain planning, agent configuration authoring. Used in interactive/conversational contexts, not in the automated notification pipeline.

Any agent at any level of the hierarchy may use any reasoning backing. The agent model is indifferent to the backing.

Practical implications:

- **Cost optimization**: Right-size the reasoning engine to the signal processing complexity. Local model for automated notification generation. Cloud API for interactive sessions. Rule-based for everything that doesn't need language understanding.
- **Model swappability**: An agent's reasoning backing can be changed without changing the agent's boundary, internal model, or signal contract.
- **Operational independence**: Local model backing means the automated notification pipeline has zero external service dependencies. Cloud LLM unavailability affects interactive sessions only, not the core notification value proposition.
- **Graceful degradation**: If the local model is unavailable, notification agents fall back to static templates. If the cloud API is unavailable, interactive sessions are unavailable but automated operation continues.

## Core Concepts

### Agents

An agent is an autonomous entity that maintains internal state, processes signals according to its own rules, and interacts with other agents exclusively through signal exchange across boundaries.

#### Domain Agent (Activity System)

The top-level agent for a life domain. Examples: "Cool-Season Lawn Care," "Zone 7a Vegetable Garden," "Virginia Whitetail Hunting," "Quarterly Health Protocol." Owns a domain-specific internal model, a set of activity agents, and a boundary definition.

Reasoning backing varies by need. Most signal processing (trigger evaluation, lifecycle transitions, prep chain scheduling) is rule-based. Some domain agents may use a local LLM for interpreting ambiguous signal combinations or generating qualitative internal model entries.

#### Activity Agent

A discrete action within a domain. Has its own lifecycle, trigger conditions, preparation chain, and follow-up steps. Operates within the signal stream already filtered by its parent domain agent's boundary. Example: "Apply Pre-Emergent Herbicide" within the Lawn Care domain agent.

Typically rule-based. Trigger evaluation, lifecycle management, and prep chain scheduling are deterministic processes operating on well-defined signal inputs.

#### Step Agent

A preparation or follow-up step within an activity. The finest-grained agent. Has completion state, timing constraints, and may have its own conditional logic (e.g., "Order supplies" step only activates if inventory signal indicates low stock).

Almost always rule-based or purely event-driven.

#### Orchestrator Agent

An agent whose role is cross-domain reasoning, configuration authoring (Phase 2+), adaptation proposals (Phase 2+), and dynamic content generation. Defined by its broad boundary, its internal model, and its signal emissions.

**Phase 1 scope**: notification content generation and interactive state querying only. Reads domain state, generates contextual notification content, answers user questions about system state during conversational sessions.

**Phase 2+ scope**: adds adaptation proposals, boundary evolution recommendations, and structural change proposals.

Reasoning backing: local LLM for notification content generation in the automated pipeline. Cloud LLM for interactive sessions (authoring, querying, complex reasoning).

The orchestrator agent is a peer, not a privileged controller. Its broad boundary means it sees more, not that it has more authority.

**Multiplicity** (Phase 3): The system may host multiple orchestrator agents with distinct boundaries, internal models, and reasoning backings.

**Internal model**: The orchestrator agent maintains its own persistent internal model:
- Cross-domain reasoning context (patterns observed across domains, seasonal planning considerations)
- User behavioral patterns ("tends to defer lawn prep in early spring," "prefers to batch Saturday activities")
- Adaptation history (Phase 2+: what changes were proposed, accepted, rejected, and their outcomes)
- Session continuity context (open reasoning threads, unresolved questions from prior conversations)
- Meta-observations about the system itself (which agents are performing well, which need attention)

#### Infrastructure Agents

Shared-service agents that provide system-wide capabilities. Each follows the same agent model.

**Notification Delivery Agent**: Absorbs notification-content signals and delivers them to the user through configured channels. Manages delivery reliability, channel fallback, quiet hours, urgency routing, and batching. Rule-based for routing and delivery logic.

**Resource Pool Agent**: Maintains the global resource inventory. Absorbs resource-demand signals and emits resource-available, resource-conflict, or low-stock signals. Rule-based.

**Aggregation Agent**: Absorbs lifecycle, notification-request, and resource-conflict signals from all domain agents. Produces the unified cross-domain view consumed by interaction surfaces. Rule-based.

**Condition Monitor Agents**: Absorb raw environmental signals and emit higher-order condition signals when compound conditions are met. Range from simple threshold scripts to ML-backed probabilistic assessors.

**System Health Agent**: Monitors operational health of the system (signal throughput, adapter liveness, agent responsiveness, storage health). Emits health-alert signals. See FR-15. Rule-based.

### Signals

Signals are the sole medium of interaction between agents and between agents and the external environment. A signal carries information and is identified by its tags. Signals do not specify a destination; they flow through the shared signal space and are absorbed or ignored based on boundary rules.

**Signal categories:**

- **Environmental signals**: weather, soil temperature, daylight hours, UV index, frost projections. Injected by data source adapters.
- **Calendar/regulatory signals**: season openers, regulatory deadlines, recurring patterns. Generated by calendar adapters or the system clock.
- **Lifecycle signals**: emitted by agents on state changes. The primary inter-agent coordination mechanism.
- **Resource signals**: emitted on resource state changes. Availability, conflicts, low stock.
- **User signals**: completions, deferrals, annotations, manual data entries, overrides, approvals/rejections.
- **Reasoning signals**: emitted by model-backed agents. Configuration proposals, adaptation proposals (Phase 2+), observation recordings, dynamic notification content, state queries.
- **Condition signals**: synthetic signals from condition monitors when compound conditions are met.
- **Approval-gate signals**: user responses to proposals. A proposal does not take effect until approved.
- **Health signals**: system health agent reports on operational status.

### Tags

Every signal carries key-value tags identifying its type, source, scope, and semantic content. Tags are the routing mechanism: boundary predicates match against tags. No centralized router exists.

Example tags on a soil temperature signal:
- signal_type: environmental
- data_type: soil-temperature
- depth: 4in
- unit: fahrenheit
- source: weather-api-xyz
- location: home-backyard
- value: 54.2
- timestamp: 2026-03-15T08:00:00Z

Example tags on a lifecycle signal:
- signal_type: lifecycle
- agent_id: lawn-care/apply-pre-emergent
- transition: watching -> preparing
- timestamp: 2026-03-15T08:05:00Z

Example tags on an adaptation-proposal signal (Phase 2+):
- signal_type: reasoning-proposal
- proposal_type: threshold-adjustment
- source_agent: orchestrator/primary
- target_agent: lawn-care/apply-pre-emergent
- field: trigger.soil_temp_threshold
- current_value: 55
- proposed_value: 52
- rationale_ref: orchestrator/primary/observation/2026-02-20-crabgrass-breakthrough
- requires_approval: true

Tags follow a system-wide taxonomy for core fields (signal_type, data_type, location, resource_id, agent_id). Domain-specific tag fields are unconstrained.

### Boundaries

A boundary is a semi-permeable membrane around an agent that determines which signals enter and which the agent emits. Boundaries are first-class configuration objects.

**Inbound boundary (absorption rules):** A set of tag-matching predicates. A signal crosses the boundary if it matches at least one predicate.

**Outbound boundary (emission rules):** Defines what signals the agent may publish and what tags it attaches. Agents cannot emit outside their declared outbound boundary.

**Hierarchical enforcement:** A child agent's inbound boundary cannot admit signals excluded by its parent's. Each level narrows, never widens.

**Boundary evolution** (Phase 2+): Orchestrator agents may propose boundary modifications based on observed signal utility, subject to user approval.

### Internal Models

Each agent maintains a persistent internal model: a structured state object whose schema is appropriate to the agent's role.

**Domain agent internal model example (Lawn Care):**
- current_phase: "spring-pre-treatment"
- treatments_this_season: [{product, date, rate_per_ksqft, conditions_at_application}]
- last_soil_test: {date, pH, N, P, K, organic_matter}
- qualitative_observations: ["minor broadleaf pressure NW corner noted 2026-03-01"]
- grass_health_score: 7/10
- historical_trigger_accuracy: [{activity, predicted_date, actual_date, outcome}]

**Orchestrator agent internal model example:**
- cross_domain_notes: ["Spring 2026: 3 overlapping prep windows mid-March across lawn, garden, hunting."]
- user_patterns: {lawn_prep_tendency: "defers until last moment", preferred_batch_day: "Saturday"}
- adaptation_outcomes: (Phase 2+) [{proposal, accepted, result, notes}]
- open_threads: ["Discuss whether to split tomato activities into separate agent"]

**Infrastructure agent internal model example (Resource Pool):**
- equipment: [{id, name, state, last_maintenance, current_holder}]
- consumables: [{id, name, quantity, unit, low_stock_threshold, last_restocked}]
- active_claims: [{resource_id, claiming_agent, claimed_at, expected_release}]

Internal models are updated through: signal-driven rules (automatic), lifecycle transitions (automatic), reasoning signals (model-backed agent observations), and user signals (annotations, manual entries).

### Niche Creation and Emergent Coordination

Agents do not coordinate through a central orchestrator. Coordination arises when one agent's emitted signals are meaningful to another agent's boundary.

**Example: Garden-to-Preservation niche.** The Vegetable Garden agent emits a lifecycle signal when "Harvest Tomatoes" completes, tagged with {crop: tomato, quantity: 15lbs}. A Fall Preservation agent's boundary admits signals matching {signal_type: lifecycle, crop: tomato, transition: *->completed}. The preservation agent's "Can Tomato Sauce" activity begins trigger evaluation. Neither agent was designed to work with the other. The niche exists because their signal tags are compatible.

**Example: Cross-domain workload niche.** The orchestrator absorbs three "preparing" signals in the same week from three domains. Its internal model flags workload conflict. It emits an observation signal surfaced to the user via the aggregation agent.

**Example: Resource contention niche.** The Lawn Care agent emits a resource-demand for the pickup truck. The Hunting agent absorbs the in-use signal and adjusts prep scheduling. The Resource Pool agent independently emits a conflict signal.

New coordination patterns form automatically when boundaries match existing signals. No explicit wiring required.

## Functional Requirements

### FR-1: Agent Definition and Configuration

**FR-1.1** The system shall accept agent definitions via structured schema. A complete agent definition includes: agent identity and hierarchy position, internal model schema, inbound and outbound boundary rules, signal processing rules, reasoning backing specification (rule-based, ML model reference, local LLM configuration, or cloud LLM configuration), resource declarations, and notification templates.

**FR-1.2** The system shall support create, read, update, and delete operations on agents via the signal interface. Configuration changes are signals, subject to boundary and approval mechanisms.

**FR-1.3** Agent definitions shall support parameterized templates. (Phase 1: templates exist but are manually instantiated. Phase 3: orchestrator can instantiate templates dynamically.)

**FR-1.4** The system shall validate agent definitions and emit structured error signals.

**FR-1.5** Agent definitions shall be versioned. Updates must not disrupt in-progress activity instances unless explicitly migrated.

**FR-1.6** The reasoning backing specification shall be modular. Changing backing shall not require changes to boundary, internal model, or signal contract.

**FR-1.7** The system shall support multiple concurrent orchestrator agents. (Phase 1: single orchestrator. Phase 3: multiple with distinct specializations.)

**FR-1.8** Infrastructure agents shall be definable using the same schema.

### FR-2: Signal Infrastructure

**FR-2.1** The system shall maintain a shared signal space. Signals are immutable once emitted.

**FR-2.2** The system shall support pluggable signal source adapters. Required adapter categories at minimum:
- Weather (current conditions, forecasts, historical normals)
- Environmental (soil temperature, daylight hours, UV index)
- Calendar/regulatory (season dates, hunting seasons, frost dates by zone)
- User-reported (manual check-ins, subjective assessments, biometric entries)

**FR-2.3** Adding a new data source requires only a new adapter. No changes to agents or infrastructure.

**FR-2.4** Condition monitor agents are first-class agents configurable through the signal interface.

**FR-2.5** Core tag fields (signal_type, data_type, location, resource_id, agent_id) follow a system-wide taxonomy. Domain-specific fields are unconstrained.

**FR-2.6** The signal space shall persist signal history durably. History must survive process restarts and be queryable for trend analysis, trigger accuracy assessment, and adaptation reasoning (Phase 2+). Retention duration configurable per signal type.

**FR-2.7** Signals shall support trust/confidence tags. Agents may factor signal confidence into trigger evaluation.

**FR-2.8** Signals shall support TTL tags. Boundaries may reject signals older than a relevance threshold for trigger evaluation while retaining them in history.

**FR-2.9** The signal space shall maintain causal ordering sufficient for compound trigger evaluation. Signals from a single source must be processed in emission order. Signals from different sources in the same compound trigger must have a defined ordering rule (timestamp-based with deterministic tie-breaking).

**FR-2.10** The signal space shall support crash recovery. On unexpected termination, the system reconstructs consistent state from persisted signals and agent state on restart without manual intervention or signal loss. Signals persisted before crash are not lost. Signals in flight at crash time are re-evaluated on restart.

### FR-3: Boundary Enforcement

**FR-3.1** Inbound boundaries: tag-matching predicates. Signal crosses if it matches at least one predicate.

**FR-3.2** Outbound boundaries: agents cannot emit signals outside their declared outbound boundary.

**FR-3.3** Hierarchical enforcement: child cannot admit what parent excludes. Validated at definition time.

**FR-3.4** Boundary rules modifiable through signal interface, subject to approval gates.

**FR-3.5** Signal absorption metrics tracked per boundary rule: match frequency and contribution to trigger evaluations, state updates, or unused. Available for boundary evolution reasoning (Phase 2+).

**FR-3.6** Model-backed agent boundaries configurable by the user independently. Sole mechanism for access control over model-backed reasoning.

### FR-4: Trigger Evaluation

**FR-4.1** Activity agents evaluate triggers continuously while in "watching" state, using only signals that crossed the activity's boundary.

**FR-4.2** Trigger types: calendar-based, signal-based, dependency-based (cross-domain via lifecycle signals), compound (AND, OR, NOT, SEQUENCE).

**FR-4.3** Signal-based triggers with uncertainty: system computes and maintains estimated firing window (earliest, most likely, latest).

**FR-4.4** Trigger conflict detection (cyclic dependencies, overlapping windows with shared resources) performed by resource pool and aggregation agents.

### FR-5: Preparation and Follow-Up Scheduling

**FR-5.1** Prep step agents activated by cascading backward from trigger point.

**FR-5.2** Uncertain trigger points: long-lead steps activate against earliest estimate; short-lead steps against confirmed/high-confidence date. Re-cascade on window shift.

**FR-5.3** Follow-up step agents activated by cascading forward from completion.

**FR-5.4** Step agents track completion; emit escalation signals if overdue.

**FR-5.5** Conditional step activation based on signal conditions at fire time.

### FR-6: Resource Management

**FR-6.1** Resource pool agent maintains global inventory via resource signals.

**FR-6.2** Activity agents emit resource-demand on entering "preparing." Resource pool emits available or conflict in response.

**FR-6.3** Low-stock signals on configurable thresholds.

**FR-6.4** Temporal conflict detection for shared equipment.

**FR-6.5** Check-in/check-out via resource-claim and resource-release signals.

### FR-7: Notification Delivery

**FR-7.1** Every notification includes LLM-generated content. The signal chain:
1. Domain or activity agent emits notification-request signal.
2. The orchestrator agent (backed by local LLM for automated pipeline) absorbs the request, reads relevant context via state signals, and generates notification content including: (a) the static criteria that drove the notification, (b) related context from the same and other domains, and (c) a rescheduling assessment given current conditions and workload. Emits notification-content signal.
3. Notification delivery agent absorbs and delivers through appropriate channel.

**FR-7.2** The LLM-generated content is the primary value, not optional decoration. The contextual synthesis across conditions, domain state, and cross-domain activity is the reason this system exists rather than a calendar with conditional reminders.

**FR-7.3** Fallback: if local LLM is unavailable, notification delivery agent uses static templates from the activity agent's definition. Fallback notifications are marked as degraded.

**FR-7.4** Each notification includes: originating agent/activity, what to do, why now, resource status, related cross-domain context, rescheduling assessment.

**FR-7.5** Urgency levels: informational, actionable, time-critical. Declared by originating agent; escalatable by step agents.

**FR-7.6** User-configurable preferences: quiet hours, channel per urgency, batching for informational.

**FR-7.7** Snooze (reschedule signal) and defer (return to watching).

**FR-7.8** At least one push-capable channel with fallback. Time-critical: at-least-once delivery.

### FR-8: Adaptation and Evolution (Phase 2)

**FR-8.1** Domain agents track historical trigger accuracy in internal models. (Phase 1: data collected. Phase 2: acted on.)

**FR-8.2** Model-backed agents propose adaptations via adaptation-proposal signals. Targets: trigger thresholds, prep lead times, resource quantities, boundary rules, internal model schema, agent structure, reasoning backing.

**FR-8.3** All proposals require user approval via approval-gate signal before taking effect.

**FR-8.4** Boundary evolution using signal absorption metrics (FR-3.5).

**FR-8.5** Structural agent changes: splitting, merging, spawning, backing changes.

**FR-8.6** Adaptation history in proposing agent's internal model. Meta-adaptation calibration.

**FR-8.7** Periodic cold review at configurable interval. System emits review-request prompting audit of recently accepted adaptations: what changed, evidence, observed outcome. Mitigates approval fatigue drift.

### FR-9: Internal Model Management

**FR-9.1** Each agent maintains persistent internal model with role-appropriate schema.

**FR-9.2** Update channels: signal-driven, lifecycle-driven, reasoning-signal-driven, user-signal-driven.

**FR-9.3** Internal models are the primary context mechanism for model-backed reasoning.

**FR-9.4** Seasonal/cyclical resets: archive and re-initialize.

**FR-9.5** Model history queryable for cross-season comparison.

### FR-10: State Access via Signal Interface

**FR-10.1** Agent-to-agent state access via state-query and state-response signals, subject to outbound boundary rules.

**FR-10.2** Cross-agent queries via aggregation agent.

**FR-10.3** Direct signal adapter queries via query signals.

**FR-10.4** User-configurable state disclosure restrictions as outbound boundary rules. This is the privacy mechanism.

### FR-11: User Interaction

**FR-11.1** Aggregation agent produces unified cross-domain timeline.

**FR-11.2** User actions (complete, skip, defer, annotate) emitted as user signals.

**FR-11.3** Resource updates emitted as user signals.

**FR-11.4** User overrides emitted as override signals, versioned, visible to model-backed agents.

**FR-11.5** Ad hoc activities and manual signals.

**FR-11.6** User-reported signals (subjective assessments, observations, notes).

### FR-12: Emergent Cross-Domain Coordination

**FR-12.1** Coordination emerges from signal exchange, not central computation.

**FR-12.2** Aggregation agent: unified timeline, workload clustering, resource conflicts.

**FR-12.3** Geographic context as signal tags; travel time factored into conflict detection.

**FR-12.4** New coordination patterns form automatically on boundary match; dissolve when signals cease.

### FR-13: Interaction Surfaces

Interaction surfaces are consumers of the aggregation agent's output and producers of user signals. They are views into and input channels for the signal space, not the system itself.

**FR-13.1** Push notifications to mobile device: mandatory primary channel for time-sensitive and actionable notifications. Notification delivery agent integrates with at least one push service (SMS, mobile push, or messaging platform webhook).

**FR-13.2** Conversational interface to orchestrator agent. The user initiates sessions (via Claude, GPT, or other chat interface with signal-emission capabilities) for: state queries, agent configuration authoring, observation recording, and complex multi-step interactions. The conversational interface is the primary surface for orchestrator interaction; push notifications are the primary surface for automated activity notifications.

**FR-13.3** Read-only dashboard or timeline view rendering aggregation agent output. At-a-glance cross-domain state: watching, preparing, ready, overdue, recently completed. May be web UI, terminal dashboard, or any rendering of summary-state signals.

**FR-13.4** All surfaces beyond FR-13.1 are additive and optional. Additional surfaces (CLI tools, calendar feed exports, etc.) are consumers of aggregation signals, requiring no core system changes.

**FR-13.5** User signals from any surface are indistinguishable in the signal space. Same tags, same processing.

### FR-14: Signal Source Quality Monitoring

**FR-14.1** Track per-adapter: signal frequency, value distribution, consistency.

**FR-14.2** Emit anomaly signals on: prolonged staleness, sudden discontinuity, out-of-bounds values, sustained deviation from correlated sources.

**FR-14.3** Anomaly notification urgency proportional to number and criticality of dependent agents.

**FR-14.4** Anomalous source: suspend trigger evaluation for affected triggers until resolved or user overrides. Silently corrupted triggers are more dangerous than paused triggers.

### FR-15: System Health and Self-Monitoring

**FR-15.1** System health agent monitors: signal throughput, adapter liveness, agent responsiveness, storage health, reasoning backing availability (local LLM process, cloud API reachability).

**FR-15.2** Dead man's switch: an **external watchdog process**, architecturally independent of the primary system, monitors system liveness. The primary system exposes a heartbeat endpoint or writes a heartbeat file. The watchdog checks liveness at a configurable interval and alerts the user through an independent channel (e.g., a cloud-based SMS service, a separate notification path) if the heartbeat is missed. The watchdog must not depend on any component of the primary system for its alerting capability. A process cannot reliably detect its own death.

**FR-15.3** On startup after unexpected shutdown: reconstruct agent state from persisted internal models, replay unprocessed signals from durable history, evaluate all triggers against current state, emit system-recovery signal summarizing downtime duration, missed signals, and affected trigger windows. Notify user of recovery and any impacted time-critical activities.

**FR-15.4** Unattended restart: no manual intervention required for full operational recovery. System registers for automatic startup with host OS.

### FR-16: LLM Authoring Workflow

**FR-16.1** The system shall accept domain definitions as self-contained structured documents. A single document shall contain the complete domain agent definition: metadata, boundary rules, internal model schema with initial values, all activity agents with triggers and step chains, resource declarations, and notification context. The system ingests this as a unit. The user never manually sequences "create domain, then add activities."

**FR-16.2** The system shall accept domain updates as structured deltas against an existing domain. A delta document specifies: activities to add, activities to modify (with the specific fields changing), activities to remove, internal model schema additions or modifications, boundary rule changes, and resource inventory updates. The system applies the delta atomically.

**FR-16.3** The structured document format shall be the sole contract between the LLM (any model, any backing) and the system. The format must be: parseable without ambiguity, validatable against the agent definition schema (FR-1.4), expressive enough for the full range of trigger types, step chains, and conditional logic (NFR-1), and authorable by an LLM from a natural conversation without the user seeing or editing the raw format.

**FR-16.4** Each activity definition shall include a `notification_context` field: static domain knowledge authored at definition time that the orchestrator agent uses as background context when generating dynamic notifications. This is not the notification text; it is the LLM's reference material for producing contextual notifications at fire time. Example: "Pre-emergent prevents crabgrass by creating a chemical barrier in the top inch of soil. It does not kill existing weeds. The barrier breaks down over 3-4 months, so application timing relative to soil temperature determines effectiveness for the full germination season."

**FR-16.5** The system shall validate all incoming definitions and deltas before applying them. Validation errors shall be returned as structured data (field path, error type, message) sufficient for the authoring LLM to diagnose and resubmit. The authoring LLM should never need to ask the user to interpret a validation error.

**FR-16.6** When an LLM authors a modification to an existing domain, the system shall provide the current domain state (internal model, active activities, current trigger estimates, resource state) as input context. The LLM produces its delta against the current state, not against the original definition.

### FR-17: Skill Architecture

The LLM's interface to this system is packaged as skills: structured prompt definitions that tell any compatible model how to interact with the system for a specific purpose. Skills are the mechanism for reasoning backing independence (NFR-11): the system does not depend on a specific model because the skill encodes the interaction contract, not model-specific instructions.

**FR-17.1** The system shall define a **Domain Authoring Skill** for use during interactive orchestrator sessions (cloud LLM). This skill instructs the LLM how to: conduct a domain planning conversation with the user, probe for trigger conditions and lead times the user might not think to specify, produce a valid domain definition in the structured format (FR-16.1), read existing domain state and produce valid deltas (FR-16.2), and validate its own output against the schema before submission.

**FR-17.2** The system shall define a **Notification Generation Skill** for use in the automated notification pipeline (local LLM). This skill instructs the LLM how to: read a notification-request signal with its associated context (domain internal model, current environmental signals, cross-domain activity state, resource state), produce the three-part notification content (what triggered this and what to do, what else is related, should this be rescheduled), and format the output as a notification-content signal. This skill must be engineered for smaller model capability: more structured input format, more explicit output format, more examples, tighter constraints on output length and scope.

**FR-17.3** The system shall define a **State Query Skill** for use in both interactive and automated contexts. This skill instructs the LLM how to: interpret system state responses, produce natural-language summaries of domain and cross-domain state, and format follow-up queries. Used by the orchestrator during conversational sessions and optionally by the local LLM for daily briefing generation.

**FR-17.4** Skills shall be versionable, testable in isolation (given sample inputs, does the skill produce valid outputs?), and portable across model backings. A skill authored for Claude should produce valid system interactions when used with Hermes, GPT, or any other compatible model, though output quality may vary with model capability.

**FR-17.5** Skills shall include: a system prompt section (role definition, output format, constraints), a schema reference section (the structured format the model must produce), and a set of examples (input/output pairs demonstrating correct authoring for representative scenarios). The examples are the primary mechanism for teaching smaller models (Hermes) to produce valid output.

## Non-Functional Requirements

### NFR-1: Schema Expressiveness
Agent definitions must encode nuanced domain knowledge without embedded code or escape hatches. The schema is the contract between domain knowledge (however authored) and the execution engine.

### NFR-2: Reliability
At-least-once delivery for time-critical notifications. Defined timeout and fallback at each stage of the notification signal chain. Missed notifications for closing action windows represent permanent value loss.

### NFR-3: Extensibility
New domain agent: no changes to existing agents or infrastructure. New signal source: new adapter only. New infrastructure capability: new infrastructure agent only. New reasoning backing: new backing adapter only. New interaction surface: new aggregation signal consumer only.

### NFR-4: Graceful Uncertainty Handling
Estimated windows, confidence levels, clear distinction between "preparing" and "time-critical." Signal confidence propagates through condition monitors.

### NFR-5: Auditability
All signal flows, boundary crossings, state transitions, internal model updates, and configuration changes logged with timestamps and causal links. Full causal chain traceable from notification to raw environmental signal.

### NFR-6: Offline and Downtime Resilience
User-offline: notifications queue, deliver on reconnection, flag missed time-critical windows. System-offline: recover from persisted state on restart (FR-15.3), backfill missed signals, notify user of impact. Assume unattended failure and unattended recovery.

### NFR-7: Privacy as Boundary Configuration
Boundary rules are the privacy mechanism. No separate permission layer required.

### NFR-8: Signal Space Performance
At single-user scale, distributed infrastructure is not required. Boundary matching, signal persistence, and history queries must remain responsive as agent count and signal volume grow. Design must not preclude future scaling but must not impose distributed-system complexity now.

### NFR-9: Agent Isolation
Misconfigured agents cannot disrupt others. Rate limiting and suspension available without system-wide impact.

### NFR-10: Fractal Consistency (Aspirational)
The agent/signal/boundary model is the target for all agent-to-agent interaction. All production signal exchange uses the signal interface. Direct read and write access to agent state, signal history, and configuration exists for debugging, administration, and operational recovery. This escape hatch is necessary because a single-operator system cannot afford to be locked out of its own internals by architectural purity. Goal: close escape hatches progressively as the signal interface proves operationally sufficient.

### NFR-11: Reasoning Backing Independence
Architecture does not depend on any specific reasoning backing. Agent boundary, internal model, and signal contract are stable across backing changes.

### NFR-12: Operational Simplicity
Every component added is a component the user maintains. Minimize independently-running processes, external service dependencies, and infrastructure components. Prefer embedded over networked, single-process over multi-process. Operational burden during normal operation as close to zero as possible. The one exception is the external watchdog (FR-15.2), which must be a separate process by definition.

### NFR-13: Failure Transparency
When something goes wrong, the system proactively informs the user rather than silently degrading. The user should never discover a failure by noticing the absence of an expected notification. Silent failure is the most dangerous failure mode for a single-operator system.

## Open Questions

1. **Orchestrator working memory scope**: How much cross-session reasoning context to persist vs. reconstruct from domain state each session?

2. **Multi-user signal attribution** (Phase 3): How to handle concurrent users on shared domain agents? Signal attribution, notification routing, concurrent state updates.

3. **Agent marketplace** (Phase 3): Can well-tuned agent definitions be shared? Parameterized templates with customization points (property size, zone, products)?

4. **Signal ordering guarantees**: Beyond FR-2.9, do compound triggers with signals from different sources need stronger causal ordering?

5. **Bootstrap**: Seed orchestrator agent definition that can self-modify through the adaptation path. How constrained should the seed be?

## Design Decisions Log

Key architectural decisions made during design, with rationale. Captures why the system is shaped this way so future sessions don't re-litigate settled questions.

### DD-1: Federated agent model over monolithic system
**Decision**: Each domain (lawn, garden, hunting, health) is an autonomous agent with its own state, not a record in a shared schema.
**Rationale**: Domains have nothing in common structurally. A shared schema is either too generic to encode useful domain knowledge or too complex to maintain. Per-domain agents with their own internal model schemas let the LLM encode domain-specific knowledge naturally. Cross-domain coordination emerges from signal compatibility, not central orchestration.
**Alternative rejected**: Flat domain/activity/step tables with a universal schema (the v1 approach). Works for initial implementation but forces awkward abstractions as domains diversify.

### DD-2: Holland's Signals and Boundaries as architectural model
**Decision**: Agents interact exclusively through tagged signals flowing across semi-permeable boundaries. No direct inter-agent API calls.
**Rationale**: Provides extensibility (new agents subscribe to existing signals without changes to existing agents), loose coupling (agents don't know about each other, only about signal tags), and emergent coordination (cross-domain patterns form automatically from signal compatibility). The formalization is not dramatically more complex than a well-designed event-driven architecture; it adds naming and structure, not fundamental complexity.

### DD-3: Agent identity is boundary + internal model + signal contract, not reasoning backing
**Decision**: An agent can be backed by a rule-based script, an ML model, a local LLM, or a cloud LLM. The backing is a swappable configuration detail.
**Rationale**: Most agents (condition monitors, step trackers, lifecycle managers) need simple rule-based logic. Only the orchestrator and notification pipeline need LLM capabilities. Tying agent identity to "uses an LLM" would conflate the execution engine with the architectural role. Separating them enables cost optimization (right-size the backing), model portability (swap providers without architectural changes), and graceful degradation (fall back to simpler backings when LLM unavailable).

### DD-4: LLM on every notification (not optional)
**Decision**: Every notification goes through LLM-backed content generation. Static templates are a degraded fallback, not the default.
**Rationale**: The three-part notification (what triggered + related context + rescheduling assessment) is the core product insight. A traditional system says "soil temp hit 55." This system says "soil temp hit 55, but rain Thursday, apply Wednesday, you have enough Barricade, and your overseeding window opens in 6 weeks." That synthesis is the entire value proposition. Making it optional means most notifications would be static, which is just a calendar with extra steps.

### DD-5: Local model for automated pipeline, cloud model for interactive sessions
**Decision**: Notification content generation runs on a local LLM (Hermes or equivalent). Interactive orchestrator sessions (domain authoring, complex reasoning) use cloud LLM (Claude or equivalent).
**Rationale**: Notification generation is constrained, single-turn, and high-frequency. Local model gives zero marginal cost, no external dependency, and no latency to remote services. The automated notification pipeline has zero external service dependencies in steady state. Cloud LLM is reserved for interactive sessions that require frontier reasoning and conversational capability.

### DD-6: Todoist retained alongside push notifications
**Decision**: Todoist sync continues as a delivery channel even after push notifications are added.
**Rationale**: v1 tested whether Todoist is a sufficient interaction surface. Rather than assume the answer, the migration path keeps both channels active and lets usage data determine which is more valuable. They may serve complementary purposes: push for time-sensitive alerts, Todoist for the "now / next / later" task view.

### DD-7: NFR-10 (Fractal Consistency) is aspirational, not enforced
**Decision**: Direct state access exists for debugging, administration, and operational recovery, outside the signal interface.
**Rationale**: A single-operator system cannot afford to be locked out of its own internals by architectural purity. If the signal processing loop is wedged and you need to manually fix an agent's state, you need direct DB access. The goal is to close these escape hatches progressively, not to pretend they're unnecessary.

### DD-8: Full infrastructure at launch, constrained surface area
**Decision**: Build the complete signal/boundary infrastructure in Phase 1, but limit agent capabilities (no adaptation, no dynamic authoring, no structural changes until Phase 2+).
**Rationale**: The infrastructure (durable event store, tag-based routing, boundary matching) is the foundation and is not dramatically more expensive than a simpler pipeline. Building a flat pipeline now means rebuilding later when extensibility is needed. Constraining the surface area (orchestrator limited to notification generation and state queries) is what controls launch complexity, not simplifying the infrastructure.

### DD-9: External watchdog for dead man's switch
**Decision**: System health monitoring uses an external process independent of the primary system.
**Rationale**: A process cannot reliably detect its own death. The watchdog must be architecturally separate: different process, different alerting channel, no shared dependencies with the primary system.

### DD-10: Skills as the LLM interface contract
**Decision**: The LLM's interaction with the system is packaged as skills (structured prompts with system instructions, schema references, and examples). Three skills: domain authoring, notification generation, state query.
**Rationale**: Skills are the mechanism for reasoning backing independence. The system doesn't depend on Claude because the skill encodes the interaction contract, not model-specific behavior. Skills are versionable, testable in isolation, and portable across model backings. The notification generation skill is specifically engineered for smaller model capability (more structured input, more examples, tighter constraints).
