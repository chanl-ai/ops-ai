# A connected app writes at once and asks the person first

Status: current on this branch. Id: `uc-721`.

A developer connects an app and can write with it straight away: every tool is on, each write in chat asks the person
first, a team admin can turn the asking off per app, a test account never asks, and a tool the team turned off says
why and how to turn it on. Generic for every app; the Apps stack's header-key desk is the worked example.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team admin turns an app on and every tool is added, writes included, each marked as asking first | api | 1-2 | 2 |
| S2 | Only a team admin turns an app's Ask before changes off; its writes then run without asking | api | 3-5 | 5 |
| S3 | A tool the team turned off is refused with the app, the tool and where to turn it on | api | 6 | 6 |
| S4 | The SDK shows the app's tools as the API does | sdk | 7 | 7 |
| S5 | In chat, a member and an admin each get Allow / Deny before a write; Allow for this chat stops the asking there | ui | 8 | 8 |

## Steps

| Step | Who and what | Expected |
|---|---|---|
| 1 | (api) Priya turns the header-key desk on | Every tool on its page is added, Close a record included |
| 2 | (api) agents-service lists the team's grantable operations | Close a record asks first; Read a record does not |
| 3 | (api) Ben, a builder, tries to turn Ask before changes off | Refused (403) |
| 4 | (api) Priya turns it off for the desk | Close a record no longer asks first |
| 5 | (api) a live run closes a record | It runs (200) with no approval |
| 6 | (api) Priya turns Close a record off; a run calls it | Refused TOOL_NOT_ADDED with the app, the tool's title and the app id |
| 7 | (sdk) James reads the desk's page through the SDK | The same tools, all added, as the API answers |
| 8 | (ui) James (member) and Priya (admin) ask the agent to close a record, at 1440 and 390 | An Allow / Deny card; Allow runs it; Allow for this chat runs the next one unasked; Deny runs nothing |

## Layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-721-api.py` | see the latest run |
| sdk | `tools-service/scripts/test-uc-721-sdk.py` | see the latest run |
| ui | not written: the chat card is proven through the real routes in `services/agents-service/tests/api/test_ask_first_chat.py` | gap |
