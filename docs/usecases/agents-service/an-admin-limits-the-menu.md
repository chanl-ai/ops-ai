# An admin limits what the menu offers

Status: draft. Service: `agents-service`. Layers: api (no ui script yet).

In this example we will set an agent to Only attached skills, then to None, and see the menu and the send follow. Design case sk-chat-8.

| Use case | |
|---|---|
| Id | `uc-750` |
| Area | Agents |
| Design label | `sk-chat-8` |
| Runs | api in its own script |
| Run it | `make usecase-test UC=uc-750` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |

## Steps

### 1. Set the agent to Only attached skills and list the menu

Expected: only the pinned skill (api script, check 1).

### 2. Send another skill, then use an agent set to None

Expected: 422 `skill_menu_limit` both times (api script, checks 2 and 3).

## What proves it

Checks 2 and 3 fail while the setting is not enforced.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, the Salesforce plugin and the team MCP address, a fake Salesforce signed in for the team, agents-service |
