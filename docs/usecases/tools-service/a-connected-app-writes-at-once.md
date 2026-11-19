# A connected app writes at once, and a team admin turns asking on

Status: current on this branch. Id: `uc-721`.

A developer connects an app and can write with it straight away: every tool is on and each write runs without asking.
A team admin can turn asking on for the team or one app, a test account never asks while the team keeps that on, and a
tool the team turned off says why and how to turn it on. Generic for every app; the Apps stack's header-key desk is the worked example.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team admin turns an app on and every tool is added, writes included, none marked as asking first | api | 1-2 | 2 |
| S2 | Only a team admin turns asking on; the app's writes then wait for approval | api | 3-5 | 5 |
| S3 | A tool the team turned off is refused with the app, the tool and where to turn it on | api | 6 | 6 |
| S4 | The SDK shows the app's tools as the API does | sdk | 7 | 7 |
| S5 | In chat, a member and an admin each get Allow / Deny before a write; Allow for this chat stops the asking there | ui | 8 | 8 |

## Steps

| Step | Who and what | Expected |
|---|---|---|
| 1 | (api) Priya turns the header-key desk on | Every tool on its page is added, Close a record included |
| 2 | (api) agents-service lists the team's grantable operations | Neither Close a record nor Read a record asks first |
| 3 | (api) a live run closes a record | It runs (200) with no approval |
| 4 | (api) a viewer tries to turn asking on | Refused (403) |
| 5 | (api) Priya, a team admin, turns asking on; the same run is made again | It is saved (200) and the write now needs an approval token |
| 6 | (api) Priya turns Close a record off; a run calls it | Refused TOOL_NOT_ADDED with the app, the tool's title and the app id |
| 7 | (sdk) James reads the desk's page through the SDK | The same tools, all added, as the API answers |
| 8 | (ui) James (member) and Priya (admin) ask the agent to close a record, at 1440 and 390 | An Allow / Deny card; Allow runs it; Allow for this chat runs the next one unasked; Deny runs nothing |

## Layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-721-api.py` | see the latest run |
| sdk | `tools-service/scripts/test-uc-721-sdk.py` | see the latest run |
| ui | not written: the chat card is proven through the real routes in `services/agents-service/tests/api/test_ask_first_chat.py` | gap |
