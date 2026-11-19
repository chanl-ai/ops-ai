# A part needing a tool the agent lacks is locked

Status: draft. Service: `agents-service`. Layers: api (no ui script yet).

In this example we will list the menu for an agent that does not hold the tool a part names and see the row locked, then try to send it. Design case sk-chat-7.

| Use case | |
|---|---|
| Id | `uc-749` |
| Area | Agents |
| Design label | `sk-chat-7` |
| Runs | api in its own script |
| Run it | `make usecase-test UC=uc-749` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |

## Steps

### 1. List the menu for the agent

Expected: the row is locked and names the tool (api script, check 1).

### 2. Send the locked part

Expected: 422 `skill_needs_scope` (api script, check 2).

## What proves it

Check 2 fails while a skill can add scope the agent lacks.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, the Salesforce plugin and the team MCP address, a fake Salesforce signed in for the team, agents-service |
