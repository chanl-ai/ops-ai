# A team holding only a workflow grant on another team's tool module uses it through the workflow and cannot edit, publish, run, revoke or delete it

Status: draft. The scripts are written but have not passed: the grant is decided in Human Tasks by a system workflow run, so the stack needs a workflow worker (lib/usecase_harness.py engine_worker) and a decision through /reviews/by-run-key, which the scripts do not do yet. Id: `uc-755`. Service: `tools-service`. Layers: api, ui. Mock mode only (no model, no real upstream).

Short title: A team holding only a workflow grant on another team's tool module uses it through the workflow and cannot edit, publish, run, revoke or delete it

## Story

As the owner of a bank module I let another team's workflow call one read, and the other team's people can see the module but change nothing of it.

## People

| Person | Role | Does what |
|---|---|---|
| James Richardson | builder, team_ops (owner) | Publishes the module and asks for the grant |
| Maya Okafor | approver, team_ops | Approves the grant |
| Desk builder | builder, Desk (second team) | Added by invite-and-accept; reads the module and is refused every change |

## In this example

The Desk team is made on the Teams page by the workspace admin. A builder joins it by invitation (never the team's creator: a creator can get 403 team_forbidden). Desk's workflow is approved for the module's read.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Desk's builder reads the module and every write, publish, run, revoke and delete answers 404 | api | 1-13 | 1 |
| S2 | The module page shows no edit controls to Desk's builder | ui | 1-5 | 2 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Desk's builder opens the module | 200, canEdit, canDelete and canPublish all false |
| 2 to 11 | Edit, add or edit an operation, publish, ask for review, run and test outside the workflow, revoke and decide the grant, delete | 404 each |
| 12 | Bulk delete | The module is skipped as not found |
| 13 | The owner reads the module | Description, operations, version and the approved grant are unchanged |
| ui 1 to 5 | The module page as Desk's builder | Operation shown; no Add operation, Import, Request security review, Edit details or enabled Delete; no Publish version; a direct edit is 404 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-755-api.py` | written, not passing |
| ui | `tools-service/scripts/test-uc-755-ui.mjs` | written, not passing |

## Non-vacuous check

Step 1 reads the module through a real grant, so the 404s that follow are the grant's limit and not a hidden module. Step 13 compares the owner's module before and after the tries.
