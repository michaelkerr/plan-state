---
name: path-authoring
description: Build a new path template (reusable season or project plan) for dispatch, or edit a custom one. Use when the user wants a plan that none of the existing paths cover ("make a template for spring garlic", "I need a plan for deer plot prep", "turn my notes into a template"), or wants to change what a custom path creates. Drafts the YAML, checks and previews it with draft_path, then saves it.
version: 1.0.0
author: plansync
---

# Path Authoring

A path is a reusable YAML template.  `instantiate` turns it into dispatch
items for one domain and one season.  You help the user write one, check
it with the `draft_path` tool, and save it.  Setting up a domain from an
existing path is the plan-state skill's job, not this one.

## Before you start

Call `status` and look at `paths`.  If an existing path already covers
the request, say so and hand off to the plan-state skill.  Built-in paths
cannot be overwritten; to change one, copy it under a new id.

## Conversation

Ask one topic at a time.  Keep the user talking about their plan, not YAML.

1. **Scope** — what season or project, and what "done" looks like.  One
   path = one season of one kind of work.  Give it an id like
   `garlic-fall` (lowercase, dashes).
2. **The work** — list the jobs in order.  For each, ask what makes it
   time to do it: a date, the weather, or another job finishing.
3. **What changes year to year** — anything that moves (frost date,
   season opener, planting date) becomes a `date` param.  Never hardcode
   a year.  Things repeated per bed/stand/zone become an `entity_ref`
   param plus `per_entity` on the item.
4. **Draft** — write the YAML (format below).  Do not show it unless the
   user asks.
5. **Check** — call `draft_path` with `yaml` and realistic sample `params`.
   Fix every error and call again until `valid` is true.
6. **Show the preview** — list each item with its `when` text.  Mention
   warnings in plain words.  Ask "does this match how you'd actually do
   it?"  Adjust and re-check.
7. **Save** — call `draft_path` with the same `yaml` and `save: true`.
8. **Offer to use it** — "Want me to set it up for this season?"  If yes,
   call `instantiate` with the path id, domain, and real params.

## Template format

```yaml
id: garlic-fall
version: "1.0.0"            # quoted
name: Fall Garlic
description: Plant in fall, mulch at first hard freeze.

params:
  - name: plant_date
    type: date              # string | number | date | list | entity_ref
    description: "Target planting date (YYYY-MM-DD)"
  - name: beds
    type: entity_ref        # list of {name: ..., properties: {...}}
  - name: mulch_depth
    type: number
    required: false
    default: 4

items:
  - ref: plant              # unique, lowercase-dashes
    name: "Plant garlic in {entity.name}"
    group: "Garlic"
    per_entity: beds        # one item per bed
    trigger:
      type: calendar
      date: "{plant_date}"
      prep_days: 3          # due 3 days before; negative = days after
    checklist:
      - label: "Break bulbs into cloves"
      - label: "Plant 2 inches deep, 6 inches apart"

  - ref: mulch
    name: "Mulch garlic"
    group: "Garlic"
    trigger:
      type: compound
      op: and
      triggers:
        - type: after
          item_ref: plant   # must be defined above
          offset_days: 14
        - type: condition
          rules:
            - metric: daily_low
              operator: "<="
              value: 28
              sustained_days: 2
    checklist:
      - label: "Spread {mulch_depth} inches of straw"
```

## Triggers

| Type | Fires when | Fields |
|---|---|---|
| `calendar` | a date arrives | `date`, `prep_days` (days before; negative = after) |
| `condition` | weather holds | `rules` (all must hold), `earliest_date` |
| `after` | another item is done | `item_ref`, `offset_days` (0 or more) |
| `compound` | a mix of these | `op` (`and`/`or`), `triggers` (2 or more) |

Condition metrics are `daily_high`, `daily_low`, `temp_high`, `temp_low`
in °F.  Operators: `>=`, `<=`, `>`, `<`, `==` (quote them).  Soil
temperature, rain, and wind are not measured — use air temperature as a
proxy and say so in the description.

Pair a condition with `earliest_date` (or a compound with a calendar
trigger) so a cool week in the wrong month does not fire it.

## Choosing items vs checklist lines

Separate item: it has its own timing (date, weather, or waits on
something).  Checklist line: it happens during the same visit as its
item.  Aim for items the user would actually want in the morning
briefing; everything else is a checklist line.

## Warnings worth fixing

- **hardcoded date** — make it a date param.
- **declared but never used** — remove the param or use it.
- **waits only on the last copy** — an `after` trigger pointed at a
  per-entity item follows only the last bed/stand.  Fine for one shared
  follow-up.  If each bed needs its own follow-up timed from its own
  planting, that is not supported yet — tell the user rather than
  pretending it works.

## Do not

- Do not write template files by hand or into the repo — save through
  `draft_path` so the file lands in the user's data directory.
- Do not save before the user has seen the preview and agreed.
- Do not evaluate the weather while authoring — the hourly job does that.
- Do not use recurrence, steps, or a `conditions` list — they are rejected.
