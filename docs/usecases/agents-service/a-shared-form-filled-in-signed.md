# A shared form filled in signed out starts a workflow with knowledge and a tool, a person approves a step, and the run finishes with a record

Status: draft, not built: the scripts are stubs that fail until written (see the hand-back). Id: `uc-756`. Service: `agents-service`. Layers: api.

Short title: A shared form filled in signed out starts a workflow with knowledge and a tool, a person approves a step, and the run finishes with a record

## Story

As a <person>, I want to <task> so that <result>.

## People

| Person | Role | Does what |
|---|---|---|
| <name> | <builder, member or admin> | <what they do here> |

## In this example

In this example we will <do X>. It assumes <Y> and <Z>.

## Stories

Four or five things a person does and sees work, in plain words, each on one layer. Its steps are rows of the steps
table below, and "Proved by" is the one step whose check shows the story works. A script names each check by its step
("2 the hold is placed"), so a run reports each story as works or broken, with the step that failed.

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A <person> <does something> and <sees the result> | api | 1 | 1 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Steps and expected results

Each step is something a person does through the public SDK, the CLI or the console. A step the product cannot do yet
stays in the table as **Open**, and a card is filed for it; the script never reaches around the product with a helper.

| # | Step | Expected |
|---|---|---|
| 1 | | |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-756-api.py` | not written |

## Non-vacuous check

Name the check that fails if the behaviour is broken, and how it was seen failing once.
