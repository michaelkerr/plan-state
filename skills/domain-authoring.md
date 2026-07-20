# Domain Authoring Skill

You are helping the user create or grow a domain plan for the plan-sync system. Your job is to run a planning conversation, then produce structured definitions that load via the `load_domain` or `add_activities` MCP tools.

## Pick the mode first

**Create mode** — the user wants to plan something new ("help me plan my garden"). You will produce a complete domain definition and call `load_domain`.

**Amend mode** — the user wants to add to something that already exists ("add tomatoes to my garden"). You will:
1. Call `get_domains` and match the user's wording to an existing domain. If it plausibly matches one, amend it — do not create a near-duplicate domain.
2. Call `get_domain_plan(domain_id)` to see what's already there: existing activities (dependencies can reference them by name), existing groups (reuse their names), current sort order.
3. Probe for just the NEW activities, using the same questions as create mode.
4. Call `add_activities(domain_id, activities=[...])` with only the new activities.

If unsure which mode applies, ask: "Add this to your existing <Domain> plan, or start a separate one?"

## What makes a domain

A domain is **one location/weather context and one coherent plan**: "Garden", "Yard", "TN Hunting Prop 1". It is NOT a broad life category ("Outdoors", "Home Stuff").

- Everything in a domain shares one weather location — condition triggers evaluate against it.
- If the user's request spans two locations (home lawn + hunting property two counties over), that's two domains.
- If the request fits an existing domain's location and theme, it's an amendment, not a new domain.

## Activity or step?

The most common authoring mistake is making everything an activity, or burying real activities as steps. The rule:

- **Needs its own trigger** — a date, a weather condition, or "after X completes" → **activity**.
- **Fixed-offset chore around a triggered event** — "3 days before", "1 day after" → **step** (prep or follow_up) on that activity.

"Order seed potatoes" 14 days before planting is a prep step. "Dig potatoes" months later when the tops die back is its own activity (it has its own trigger), linked by dependency — not a follow-up step.

## Grouping with group_name

`group_name` is a free-form bundle label within a domain — a crop, a bed, a species, a zone. It is **display-only**: briefings and task lists bundle grouped items together, and task names get the prefix "Group: Task". Trigger logic NEVER comes from groups — sequencing between activities is expressed with dependency triggers.

Use a group whenever one real-world thing spans multiple activities. The canonical pattern is a multi-phase crop as a dependency chain under one group:

- "Start Tomato Seeds" (calendar trigger) — group "Tomatoes"
- "Transplant Tomatoes" (dependency: after "Start Tomato Seeds" + offset) — group "Tomatoes"
- "Tomato Harvest Watch" (dependency or calendar) — group "Tomatoes"

Steps inherit their parent activity's group automatically. Single-activity topics (e.g. one-off admin tasks) can stay ungrouped. In amend mode, reuse the domain's existing group names where they fit — check `get_domain_plan` output before inventing new ones.

## Conversation flow

### 1. Understand the scope

- Create mode: What domain? What location (city, state — e.g. "Murfreesboro,TN,US")? What time horizon? Constraints (zone, size, equipment)?
- Amend mode: fetch the domain plan first, then just: what's being added, and how does it relate to what's there?
- If the user already provided most of this, don't re-ask.

### 2. Probe each activity

**Trigger**: When should this happen?
- Fixed date → calendar
- Weather-dependent → condition (what metric? threshold? consecutive days?)
- After another activity completes → dependency (which one? days after? — in amend mode this can be an EXISTING activity's name)
- Date window AND weather → compound

**Prep steps**: What must happen before? How many days before each? Commonly forgotten: ordering supplies, checking inventory, equipment maintenance, scheduling helpers.

**Follow-up steps**: What happens after? How many days after? Common: watering in, monitoring, second application, cleanup.

**Group**: Is this part of a multi-activity bundle (crop, bed, species)? Same group for every phase of it.

### 3. Look for gaps

- Dependency chains: does anything here depend on something else completing — including activities already in the domain?
- Are lead times realistic? (14 days to order supplies, not 1.)
- Condition thresholds: did the user state them, or are you guessing? If guessing, ask.
- Missing companions: "you mentioned fall aeration but not overseeding — do those go together?"
- Multi-phase things authored as one activity: should this split into a dependency chain under one group?

### 4. Produce the definition

Activity format (used by both `load_domain` and `add_activities`):

```json
{
  "name": "Activity Name",
  "description": "What this is and why it matters",
  "group_name": "Tomatoes",
  "trigger_type": "calendar|condition|dependency|compound",
  "trigger_def": { ... },
  "sort_order": 1,
  "steps": [
    {"name": "Step name", "step_type": "prep|follow_up", "lead_days": 7, "description": "Optional"}
  ]
}
```

Do NOT include a `conditions` array — the system derives condition rows automatically from the condition-type leaves of `trigger_def`, and definitions that include an explicit `conditions` field are rejected.

Create mode wraps activities in a domain:

```json
{
  "name": "Domain Name",
  "location": "City,ST,US",
  "notes": "Zone, constraints, relevant context",
  "activities": [ ... ]
}
```

### 5. Load it

- Create: `load_domain(definition=<domain object>)`
- Amend: `add_activities(domain_id=<id>, activities=[<new activities>])`

If the tool returns validation errors, fix them and retry. Show the user what was created, then call `get_upcoming()` to show what's coming up.

## Trigger definition reference

### Calendar
```json
{"type": "calendar", "date": "2027-03-15"}
```

### Condition
```json
{
  "type": "condition",
  "all": [
    {"metric": "daily_high", "operator": ">=", "value": 55, "sustained_days": 3}
  ]
}
```

Available metrics: `daily_high`, `daily_low`, `temp_high`, `temp_low`
Operators: `>=`, `<=`, `>`, `<`, `==`

Note: `soil_temp` is not supported (no data source supplies it) and is rejected by validation. Use `daily_high` as a proxy for soil warming.

### Dependency
```json
{
  "type": "dependency",
  "activity_ref": "Name of Other Activity",
  "event": "completed",
  "offset_days": 14
}
```

Use `activity_ref` (the activity name) — the system resolves names to IDs at load. In amend mode, `activity_ref` may name an activity already in the domain.

### Compound
```json
{
  "type": "compound",
  "operator": "AND",
  "conditions": [
    {"type": "calendar", "after": "2027-08-15"},
    {
      "type": "condition",
      "all": [
        {"metric": "daily_high", "operator": "<=", "value": 85, "sustained_days": 3}
      ]
    }
  ]
}
```

Use compound when the trigger requires BOTH a date window AND a weather condition. This is common — most condition-based activities have an earliest possible date. Prefer compound over pure condition triggers.

## Complete examples

### Create mode

```json
{
  "name": "Cool-Season Lawn Care",
  "location": "Richmond,VA,US",
  "notes": "Zone 7a, ~8000 sqft tall fescue. Irrigated.",
  "activities": [
    {
      "name": "Apply Pre-Emergent Herbicide",
      "description": "Granular pre-emergent to prevent crabgrass. Must go down before sustained warm temps.",
      "group_name": "Weed Control",
      "trigger_type": "compound",
      "trigger_def": {
        "type": "compound",
        "operator": "AND",
        "conditions": [
          {"type": "calendar", "after": "2027-02-15"},
          {
            "type": "condition",
            "all": [
              {"metric": "daily_high", "operator": ">=", "value": 55, "sustained_days": 3}
            ]
          }
        ]
      },
      "sort_order": 1,
      "steps": [
        {"name": "Check herbicide inventory", "step_type": "prep", "lead_days": 14, "description": "Need 4 lbs for 8000 sqft"},
        {"name": "Order if needed", "step_type": "prep", "lead_days": 10},
        {"name": "Calibrate spreader", "step_type": "prep", "lead_days": 1},
        {"name": "Water in application", "step_type": "follow_up", "lead_days": 1, "description": "0.5 inches to activate"}
      ]
    },
    {
      "name": "Spring Fertilizer",
      "description": "Light nitrogen after grass is actively growing. 3 weeks after pre-emergent.",
      "group_name": "Feeding",
      "trigger_type": "dependency",
      "trigger_def": {
        "type": "dependency",
        "activity_ref": "Apply Pre-Emergent Herbicide",
        "event": "completed",
        "offset_days": 21
      },
      "sort_order": 2,
      "steps": [
        {"name": "Check fertilizer inventory", "step_type": "prep", "lead_days": 7},
        {"name": "Mow before applying", "step_type": "prep", "lead_days": 1},
        {"name": "Water in fertilizer", "step_type": "follow_up", "lead_days": 1}
      ]
    }
  ]
}
```

### Amend mode

User: "Add tomatoes to my garden." After `get_domains` finds "Garden" and `get_domain_plan` shows its beds and activities:

```
add_activities(domain_id="<garden id>", activities=[
  {
    "name": "Start Tomato Seeds Indoors",
    "group_name": "Tomatoes",
    "trigger_type": "calendar",
    "trigger_def": {"type": "calendar", "date": "2027-02-20"},
    "steps": [
      {"name": "Order tomato seeds", "step_type": "prep", "lead_days": 14},
      {"name": "Set up seed trays and lights", "step_type": "prep", "lead_days": 2}
    ]
  },
  {
    "name": "Transplant Tomatoes",
    "group_name": "Tomatoes",
    "trigger_type": "dependency",
    "trigger_def": {"type": "dependency", "activity_ref": "Start Tomato Seeds Indoors", "event": "completed", "offset_days": 49},
    "steps": [
      {"name": "Harden off seedlings", "step_type": "prep", "lead_days": 7},
      {"name": "Prep bed with compost", "step_type": "prep", "lead_days": 3},
      {"name": "Water in transplants", "step_type": "follow_up", "lead_days": 1}
    ]
  },
  {
    "name": "Tomato Harvest Watch",
    "group_name": "Tomatoes",
    "trigger_type": "dependency",
    "trigger_def": {"type": "dependency", "activity_ref": "Transplant Tomatoes", "event": "completed", "offset_days": 60},
    "steps": [
      {"name": "Check daily for ripeness, pests, blossom end rot", "step_type": "follow_up", "lead_days": 1}
    ]
  }
])
```

Note the pattern: one crop, one group, three activities in a dependency chain. The dependency refs could equally name activities that already existed in the domain.

## Important rules

- Every activity MUST have `name`, `trigger_type`, and `trigger_def`. Steps and conditions are optional but recommended.
- **Never include a `conditions` array** — condition rows are derived automatically from the condition-type leaves of `trigger_def` at load/update time, and an explicit `conditions` field fails validation. `trigger_def` is the single source of truth for when an activity fires.
- Use `activity_ref` (name string) for dependencies, NOT `activity_id`.
- Activity names must be unique within the domain — in amend mode, check `get_domain_plan` output for collisions before loading.
- `lead_days` must be 0 or positive. Prep steps count backward from the trigger date, follow-ups forward.
- `sort_order` controls display ordering. In amend mode you may omit it — new activities are appended after existing ones.
- Do not include `status` or `id` fields — the system assigns these.
- If the user gives vague timing ("sometime in spring"), ask for specifics. If they don't know, use a compound trigger with a calendar `after` date plus a condition.
- When in doubt about lead times, err on the side of more time. It's easier to skip a prep step than to rush one.
