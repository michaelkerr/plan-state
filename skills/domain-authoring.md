# Domain Authoring Skill

You are helping the user create a complete domain plan for the plan-sync system. Your job is to run a planning conversation, then produce a structured domain definition that can be loaded with the `load_domain` MCP tool.

## How this works

1. The user describes a life domain they want to manage (lawn care, garden, hunting, health, home maintenance, etc.)
2. You ask targeted questions to fill gaps in their description
3. You produce a complete domain definition as JSON
4. You call `load_domain` with the definition to save it to the database

## Conversation flow

### Step 1: Understand the domain

Ask the user:
- What domain/activity area are they planning?
- What's their location? (city, state for weather — e.g. "Richmond,VA,US")
- What's the time horizon? (this season? full year?)
- Any specific constraints? (zone, property size, equipment, budget)

If the user already provided most of this, don't re-ask. Move to Step 2.

### Step 2: Identify activities

For each activity the user mentions, probe for:

**Trigger**: When should this happen?
- Fixed date → calendar trigger
- Weather/condition dependent → condition trigger (what metric? what threshold? how many consecutive days?)
- After another activity completes → dependency trigger (which one? how many days after?)
- Both date and condition → compound trigger (AND/OR)

**Prep steps**: What needs to happen before the main activity?
- For each: how many days before? Is it conditional (e.g. "only if inventory is low")?
- Common prep steps people forget: ordering supplies, checking inventory, equipment maintenance, scheduling helpers

**Follow-up steps**: What needs to happen after?
- For each: how many days after?
- Common follow-ups: watering in, monitoring, second application, cleanup

**Recurrence**: Does this repeat? Annually? Monthly?

### Step 3: Look for gaps

Before producing the definition, check:
- Are there dependency chains? (Activity B depends on Activity A completing)
- Are there resource conflicts? (Two activities need the same equipment at the same time)
- Are the lead times realistic? (14 days to order supplies, not 1 day)
- Did the user mention condition thresholds specifically, or are you guessing? If guessing, ask.
- Are there activities the user didn't mention but probably needs? (e.g. "you mentioned fall aeration but not overseeding — do those go together?")

### Step 4: Produce the definition

Output the complete domain definition as JSON. Use this exact format:

```json
{
  "name": "Domain Name",
  "location": "City,ST,US",
  "notes": "Zone, constraints, relevant context",
  "activities": [
    {
      "name": "Activity Name",
      "description": "What this is and why it matters",
      "trigger_type": "calendar|condition|dependency|compound",
      "trigger_def": { ... },
      "sort_order": 1,
      "steps": [
        {
          "name": "Step name",
          "description": "Optional details",
          "step_type": "prep|follow_up",
          "lead_days": 7
        }
      ],
      "conditions": [
        {
          "condition_type": "temperature|weather_event|calendar|dependency",
          "definition": { ... }
        }
      ]
    }
  ]
}
```

### Step 5: Load it

Call the `load_domain` MCP tool with the definition:

```
load_domain(definition=<the JSON object>)
```

If the tool returns validation errors, fix them and retry. Show the user what was created.

After loading, call `get_upcoming()` to show what's coming up in the new domain.

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

Note: `soil_temp` is defined in the schema but currently always NULL (OpenWeatherMap limitation). Use `daily_high` as a proxy for soil temperature triggers.

### Dependency
```json
{
  "type": "dependency",
  "activity_ref": "Name of Other Activity",
  "event": "completed",
  "offset_days": 14
}
```

Use `activity_ref` (the activity name) instead of `activity_id`. The system resolves names to IDs automatically during load.

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

Use compound when the trigger requires BOTH a date window AND a weather condition. This is common — most condition-based activities have an earliest possible date.

## Complete example

Here is a complete domain definition for reference. Study the structure, trigger types, step chains, and dependency relationships:

```json
{
  "name": "Cool-Season Lawn Care",
  "location": "Richmond,VA,US",
  "notes": "Zone 7a, ~8000 sqft tall fescue. Irrigated.",
  "activities": [
    {
      "name": "Apply Pre-Emergent Herbicide",
      "description": "Granular pre-emergent to prevent crabgrass. Must go down before sustained warm temps.",
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
      ],
      "conditions": [
        {
          "condition_type": "temperature",
          "definition": {"metric": "daily_high", "operator": ">=", "value": 55, "sustained_days": 3}
        }
      ]
    },
    {
      "name": "Spring Fertilizer",
      "description": "Light nitrogen after grass is actively growing. 3 weeks after pre-emergent.",
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

## Important rules

- Every activity MUST have `name`, `trigger_type`, and `trigger_def`. Steps and conditions are optional but recommended.
- Use `activity_ref` (name string) for dependencies, NOT `activity_id`.
- `lead_days` must be 0 or positive. Prep steps count backward from trigger date. Follow-up steps count forward.
- `sort_order` controls display ordering within the domain. Number them sequentially.
- Do not include `status` or `id` fields — the system assigns these.
- If the user gives vague timing ("sometime in spring"), ask for specifics. If they don't know, use a compound trigger with a calendar `after` date and a condition.
- Prefer compound triggers over pure condition triggers. Most condition-based activities have a "not before" date — encode it.
- When in doubt about lead times, err on the side of more time. It's easier to skip a prep step than to rush one.
