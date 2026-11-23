# A builder takes a new skill to its first publish in under ten minutes

Status: current. Id: `uc-771`. Service: `agents-service`. Layers: ui.

The first Ops AI milestone (skill and workflow editors) says a builder goes from a new skill to its first publish in
under ten minutes. This use case times that walk. James starts on the skills list, makes a skill, writes a short
plain-text SOP with one guard ("Never refund over 500 without a manager approving it"), saves it and sends it for
review; Maya opens the text diff and approves; the skill shows as published. The script prints the wall-clock seconds
of each step and the total, and the clicks and typed fields a person needed. The seconds are the console's and the
services' response time with a script driving; a person reading and thinking adds to them.

## People

| Person | Role | Does what |
|---|---|---|
| James Richardson | builder, team_ops | Creates the skill, writes the text, sends it for review |
| Maya Okafor | publisher, team_ops | Reads the text diff and approves |

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder takes a new skill from the skills list to its first publish within ten minutes | ui | 1-9 | 1 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Publish review on for skills in team_ops | The script sets it as Priya (`publishReviewOn`); not timed |
| One skill already owned by team_ops | The script makes it through the API; not timed. See the open finding |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens the skills list | New skill is offered |
| 2 | New skill: name, use when, Create | The skill page opens on the text editor |
| 3 | Select all, write the SOP with one guard | The guard line is in the text |
| 4 | Save the draft | The save state reads saved |
| 5 | Publish, say what changed, Send | The page shows the skill waiting in Reviews |
| 6 | Maya signs in | The console opens |
| 7 | Maya opens the request | The Text section shows the added lines, including the guard |
| 8 | Maya approves | The decision answers 200 |
| 9 | James reloads the skill | It shows v1 published |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-771-ui.mjs` | `make usecase-test UC=uc-771 LAYER=ui` |

## Non-vacuous check

Check 1 fails when any step fails or the total is over 600 seconds (`UC771_BUDGET_SECONDS` lowers it for a try). Seen
failing: with the budget at 3 seconds the run printed `FAIL 1 a new skill goes from the list to published in 3 s, under
3 s`; before the seed skill existed, step 2 failed on the New skill dialog.

## Open finding

On a team that owns no skill yet, New skill cannot be completed. The Owner team select lists only the teams that
already own a skill (`GET /v1/skills/options` builds `teams` from existing skills, `routers/skills.py`), so it shows
"Choose a team", and Create skill answers "Choose the owner team." with no way to choose one. Generate skill and From a
template are other ways to the first skill. This script seeds one skill through the API to get past it.
