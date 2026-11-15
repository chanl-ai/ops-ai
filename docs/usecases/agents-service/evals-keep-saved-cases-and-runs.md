# Evals keep saved cases and runs for the team

Status: draft. Id: `uc-751`. Service: `agents-service`. Layers: api, sdk, ui.

Short title: Evals keep saved cases and runs for the team

## Story

As a builder, I want test cases saved on an agent and every run of them kept, so that a model risk reviewer can see on
Govern > Evals which suites fail and which publish requests would be held, and my team alone sees them.

## People

| Person | Role | Does what |
|---|---|---|
| James Richardson | builder, team Ops | Saves two cases on an agent and runs them twice |
| Ravi Menon | viewer, team Ops | Reads suites and runs, cannot save cases |
| Priya Shah | admin, team Ops | Reads the Evals page |
| Wanjiru Kamau | admin, team Platform | A member of another team: sees none of it |

## In this example

In this example James saves two cases on the Branch Concierge agent and runs them twice. It assumes the seeded people
and agents and the scripted model, so no real model is called.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder saves cases, runs them twice and a viewer reads both runs, newest first | api | 1, 2, 3, 4, 5 | 2 |
| S2 | A member of another team sees no suite or run and cannot touch the cases | api | 6 | 6 |
| S3 | Evidence and judges are not offered while nothing backs them | api | 7 | 7 |
| S4 | The same flow works through the Python SDK, and another team still sees nothing | sdk | 11, 12, 13, 14, 15 | 15 |
| S5 | An admin and a viewer open Govern > Evals: three tabs, counts equal rows, no sample data | ui | 1, 2, 3, 4, 5, 6 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A builder saves two cases on an agent | 200 with both cases listed |
| 2 | The builder runs the saved cases twice | Two runs with different ids, not an overwrite |
| 3 | A viewer reads the Runs tab | Both runs, newest first, with the agent's name |
| 4 | The viewer reads the Suites tab | One suite with two cases; the tab counts equal its rows |
| 5 | The viewer tries to save cases | 403 |
| 6 | A member of another team reads suites and tries to save | No rows, zero runs counted, 404 on save |
| 7 | Anyone reads the tab counts and asks for Evidence | Only suites, runs and gates are counted; 404 for evidence |
| 11 to 15 | The same through the Python SDK | As steps 1 to 6 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-751-api.py` | written |
| sdk | `agents-service/scripts/test-uc-751-sdk.py` | written |
| ui | `agents-service/scripts/test-uc-751-ui.mjs` | written |

## Non-vacuous check

Step 6 (another team's agent: no rows, and 404 on save). It fails if the reads or the save skip the team filter; the unit
test `test_another_teams_suites_runs_and_counts_are_never_shown` was seen failing before the filter was in place.
