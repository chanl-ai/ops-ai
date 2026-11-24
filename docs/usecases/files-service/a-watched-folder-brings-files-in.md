# A watched folder brings files in

Status: current on the branch. Id: `uc-772`. Service: `files-service` with tools-service. Layers: api, ui.

Short title: A watched folder brings files in

## Story

As a builder, I want to watch a SharePoint folder from Files so that each file in it arrives in Files by itself, and a
file the check could not bring in is named on the folder's row with the reason and its size.

## People

| Person | Role | Does what |
|---|---|---|
| Priya Shah | admin of `team_ops` | Connects SharePoint for the team (through the API, as uc-678 proves) |
| Sam Adeyemi | security admin | Allows the SharePoint hosts and the fake's address |
| James Richardson | builder of `team_ops` | Watches the Policies Library, presses Check now, opens a file it brought in |
| Ravi Menon | viewer of `team_ops` | Reads the watched folders and their files; may not add or check one |

## In this example

James watches the Policies Library of the Human Resources site. The library holds `leave.md`, `expenses.txt`,
`travel.pdf` and `scanned-contracts-2026.zip`, which Graph reports as 30 MB, over the 25 MB a watch takes. One check
brings the three small files in and names the zip as failed with its size. It assumes the team has the SharePoint app
and its Microsoft sign-in, which a fake Graph and a fake Microsoft sign-in serve on this machine
(`docs/usecases/lib/fake_sharepoint_confluence.py`; the ui script starts it with `--oversize`).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A viewer reads the watched folders and their events, and adding or checking one is refused; another team does not find it | api | 2-3, 6 | 3 |
| S2 | Check now brings the folder's files in, says a second press is already running, and names the file over 25 MB with its size | api | 4-7 | 5 |
| S3 | With SharePoint not yet on for the team, Watch a folder says no connection can list files, opens Apps and keeps Next disabled | ui | 11 | 11 |
| S4 | A builder watches a folder, presses Check now, sees it running, then the time, the count and the failed file with its size; the file's page names its source | ui | 12-15 | 14 |
| S5 | A viewer sees the same list with no Watch folder or Check now, and a direct add or check is refused | ui | 16 | 16 |
| S6 | Knowledge's Add source keeps its SharePoint step 2, and the list draws its loading, empty and error states at both widths | ui | 17-19 | 17 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The SharePoint plugin with `files: true` on its files source | the plugins checkout (`OPS_PLUGINS_REPO`; beside the main checkout by default) |
| platform-service, tools-service, files-service, kb-service | api: started by the script; ui: by `withUiStack` with platform sign-in |
| People | the dev seed; password `northfield-demo` |

## Steps and expected results

Steps 1-7 are the api script (`test-uc-772-api.py`); steps 11-19 the ui script (`test-uc-772-ui.mjs`), every screen at
1440 and 390 wide.

| # | Step | Expected |
|---|---|---|
| 1 | Sam allows the hosts; Priya connects SharePoint through Microsoft | The sign-in completes (200) |
| 2 | James adds a watch on the Policies Library with the picker's names | 201, and the watch names Human Resources and Policies Library |
| 3 | Ravi lists the watches, then adds one and presses Check now; Sam reads the watch from team_security | The list has the watch; both writes are 403; the other team gets 404 |
| 4 | James presses Check now twice | 202, the watch says it is checking, and the second press is 409 "already checking" |
| 5 | The check ends | 3 brought in, 1 failed: `scanned-contracts-2026.zip`, 31457280 bytes; 3 files in Files |
| 6 | Ravi reads the watch's events | Three `new` events and one `failed` event with its size |
| 7 | Ravi opens `leave.md` | Its source names the watch and its path in the library |
| 11 | Before SharePoint is on for the team, James opens Watch a folder | "No connection can list files", one link to Apps (`/data/connectors`), Next disabled reading "connect an app first", as the design's no-connection state draws it |
| 12 | The team connects SharePoint (API) | The sign-in completes |
| 13 | James names the watch, picks Human Resources and Policies Library, reaches the review and saves | The review names both folders and says everyone on the team can read the files; 201 |
| 14 | James presses Check now in the row menu | The row shows Checking…, then, without a reload, the time, "3 files brought in" and the zip with its size in MB, matching the events route |
| 15 | James opens `leave.md` | The Source section names the watch and `… › Policies › leave.md` |
| 16 | Ravi opens Watched folders | The row shows with its failed file; no Watch folder and no row menu; a direct add and Check now are 403 |
| 17 | James opens Add source on a knowledge base and picks SharePoint | Step 2 shows the name, the sites and libraries pickers, Include and Exclude, and no preview (the SharePoint source declares none) |
| 18 | The list's GET is held, emptied and refused | The skeleton, "No watched folders yet" with Watch folder, and "Couldn’t load watched folders" with Try again |
| 19 | Every screen | No sideways scroll and no page or console errors (the refused request's own console line is not counted) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `files-service/scripts/test-uc-772-api.py` | passing |
| ui | `files-service/scripts/test-uc-772-ui.mjs` | see the latest run |

## Non-vacuous check

api step 5 fails when the check cannot reach SharePoint or a refused file loses its size: it failed with "caller
identity is not registered" until files-service was listed among the gateway's callers
(`services/tools-service/policy/data.json`), and with `size: None` until the SharePoint listing row carried Graph's
size. Step 3's 403s are paired with step 2 and 4's successes for James, so a route open to everyone fails it. Step 13
fails when the SharePoint source loses `files: true`: the dialog then offers no connection to pick.
