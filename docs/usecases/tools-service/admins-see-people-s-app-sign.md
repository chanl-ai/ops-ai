# Admins see people's app sign-ins and end one

Status: current, 2026-11-22. Id: `uc-770`. Service: `tools-service`. Layers: ui.

Short title: Admins see people's app sign-ins and end one

## Story

As a team admin, I want to see who signed in to which of the team's apps and end one person's sign-in, so that I can
stop agents acting as that person in one app without turning the app off for everyone.

## People

| Person | Role | Does what |
|---|---|---|
| Priya Shah | Operations admin | Adds Claims desk, reads Apps and People, ends James's sign-in |
| James Richardson | Operations builder | Gives his own Claims desk key; is not offered People |
| Ravi Menon | Operations viewer | Gives his own Claims desk key; opens the Salesforce app page |

## In this example

In this example Priya adds Claims desk, a key app each person signs in to. James and Ravi give their own keys, as My
apps does. Priya reads the Apps table and the People page at 1440 and 390 wide and ends James's sign-in from his
sheet; James's My apps card then says an admin ended it. It runs on the use case's own stack, never the shared one.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Priya sees each app's sign-in health in the Apps table, with no content pack listed | ui | 1, 4 | 1 |
| S2 | Priya sees each person's sign-ins counted as the server counts them | ui | 2, 4 | 2 |
| S3 | Priya ends James's sign-in; his row counts it refused and his My apps card says an admin ended it | ui | 3, 5 | 3 |
| S4 | James is not offered People, and a direct visit names the permission it needs | ui | 5 | 5 |
| S5 | The Salesforce app page loads for an admin and a viewer with no failed request | ui | 6 | 6 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The console build and the services | `withUiStack` starts them for the run |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya opens Apps (`/data/connectors`) at 1440 | A table by default; Claims desk reads "Each person" and "2 connected"; no Core case and task types row; an Apps and a People tab |
| 2 | Priya opens People | James and Ravi, one row each, Connected counts equal to `GET /v1/apps/people` |
| 3 | Priya opens James's row and ends his Claims desk sign-in | The sheet's badge reads Ended by an admin with no End sign-in left; his row's Couldn't connect reads 1; the server counts connected 0, refused 1 |
| 4 | Priya opens Apps and People at 390 | Neither page scrolls sideways |
| 5 | James opens Apps, then `/data/connectors/people`, then My apps | No People tab; the API answers 403; the page names Manage on Connections; his Claims desk card reads "Ended by an admin" |
| 6 | Priya and Ravi open the Salesforce app page | `GET /v1/apps/plugin:opsai.salesforce` answers 200 and no request answers 5xx |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `tools-service/scripts/test-uc-770-ui.mjs` | written |

## Non-vacuous check

Step 3 fails when End sign-in leaves the sign-in working (the badge never reads Ended by an admin and the server's
refused count stays 0); step 5 fails when People is offered to a builder or its refusal names no permission. The
server tests behind them (`services/tools-service/tests/test_apps_people.py`) were each seen failing with their fix
reverted.
