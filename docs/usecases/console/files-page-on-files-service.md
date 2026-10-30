# A builder works the Files page on files-service

Status: current. Id: `uc-112`. Service: `console`. Layers: ui.

Card an earlier change: the Files page reads files-service. Views, counts, search and the uploaded range run in its query; the
sheet shows what uses a file; delete goes through the delete guard; legal holds are for admins of the team.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder of team_ops), Priya Shah (admin of team_ops); password `northfield-demo` |
| Three files in team_ops | uploaded by James through `/v1/files/uploads`; one used by a chat message through files-service's internal references route (a dev service token) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Files | the three files, "All · 3", the page from files-service; no Team column; no legal hold actions for him |
| 2 | He searches one name | that file only, answered by the service |
| 3 | He opens the used file | the sheet names the team (Operations, not `team_ops`) and says "Not scanned"; "Used by · 1" names the chat message; Delete is disabled with the reason |
| 4 | He downloads it | the bytes arrive through the service |
| 5 | He deletes an unused file | it leaves the list |
| 5b | James presses Upload, chooses Knowledge source and drops a new text file | The dialog offers upload only, with the purpose's types and size; once the file is stored and scanned, Add closes it and the file is listed with that purpose |
| 6 | Priya places a legal hold on a file, pressing Enter after the reason | "Under legal hold · 1"; the sheet's Storage section is for admins of the file's team and names the backend "Local disk"; at 400 px the sheet footer keeps prev and next on screen |

## Acceptance layers

| Layer | Script |
|---|---|
| ui | `docs/usecases/console/scripts/test-uc-112-ui.mjs` |
