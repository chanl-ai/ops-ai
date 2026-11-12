# A pick over the reply's budget is refused

Status: draft. Service: `agents-service`. Layers: api, ui.

In this example we will pick a third part when two skills already fill the reply and see the send refused before the model is called. Design case sk-chat-6.

| Use case | |
|---|---|
| Id | `uc-748` |
| Area | Agents |
| Design label | `sk-chat-6` |
| Runs | api and ui in their own scripts |
| Run it | `make usecase-test UC=uc-748` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |

## Steps

### 1. Publish a part over 6,000 tokens

Expected: publish refused (api script, check 1).

### 2. Pick a third part in a reply that already holds two

Expected: 422 `skill_budget` naming which skills hold the room (api script, check 2).

## What proves it

Check 2 fails while a pick can pass the cap.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack and the team MCP address, agents-service |
