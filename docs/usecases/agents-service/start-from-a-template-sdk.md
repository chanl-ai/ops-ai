# Start a skill from a template through the SDK

Status: draft. Id: `uc-740`. Service: `agents-service`. Layers: sdk.

In this example we will list the templates offered to a team, one kind at a time, install the starter skill
"Doc co-authoring" and find it in the team's skills, all through the Python SDK. It assumes the starters pack is on for team_ops and Priya, the team's admin, is signed in.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `ops.templates.list(kind=...)` for agent, skill, workflow, guardrail, case type and task type | Each list holds only its kind; the skill list offers `plugin:opsai.starters:doc-coauthoring` with `canAdd` |
| 2 | `ops.templates.install("plugin:opsai.starters:doc-coauthoring")` | `created: true` and the copy's record id |
| 3 | `ops.raw.agents.agents_list_skills()` | The new skill is in the team's list |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| sdk | `agents-service/scripts/test-uc-740-sdk.py` | red: no `templates` words in the SDK, no starters pack |

## Non-vacuous check

Step 1 fails while the SDK has no `templates.list`; step 2 fails while the starters pack is missing.
