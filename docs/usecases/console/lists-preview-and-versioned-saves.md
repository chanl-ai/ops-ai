# Lists tab once per row, mock-backed pages say Preview, versioned settings save from the button

Status: current. Id: `uc-106`. Service: `console`. Layers: ui.

Card an earlier change: a table row that opens on click holds one named control (a link, or a button when it opens a sheet) in
its name cell and no `tabindex` of its own. Pages that still show mock data while real services answer beside them
carry a Preview badge in the page header and the sidebar. Settings that save a new version on each save do not save
on Enter.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder of team_ops) creates guardrails; Maya Okafor (reviewer) reads the list; Sam Adeyemi (Security admin) edits Storage; password `northfield-demo` |
| Storage settings | files-service, on withUiStack's default stack |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James creates 25 guardrails with one name prefix; Maya opens Guardrails, searches the prefix and shows 30 rows a page | 25 rows, none with a `tabindex`, each holding one link to its record |
| 2 | Maya puts the focus on the first row's link and presses Tab until the focus reaches the pagination | 73 stops inside the table (three per row: select, copy id, record link; counted from the first row's link) and at most 3 between the last row and the pagination; counting from the table means a filter added to the toolbar does not move the bar |
| 2b | Maya opens Tools, Widgets and Connections | the first row of each holds a link to its record and no `tabindex` |
| 2c | Maya, at 400px wide, searches Guardrails for a name nothing matches | the empty message and its Clear filters button sit inside the viewport |
| 2d | James opens a skill's Instructions tab | the add-tool button is named "Add a tool operation", the text on it |
| 3 | Sam, a Security admin, opens Storage, changes the signed link lifetime and presses Enter | no version is saved |
| 4 | He clicks the Save button | "Saved as version" |
| 5 | Sam opens Settings (Members), where nothing is served by a service | a Preview badge in the header, and on the Settings row of the app sidebar when read from a page outside Settings (Settings has its own sidebar); Files and Access carry none, since files-service and platform-service serve them |
| 6 | He opens Egress, which tools-service serves | no badge in the header |
| 7 | He opens Wiki and Model inventory, then Guardrails | Wiki and Model inventory carry the badge (no service URL serves them); Guardrails does not (agents-service) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-106-ui.mjs` | passing (13/13) |

## Non-vacuous check

Run with `tabIndex={0}` put back on the row: steps 1 and 2 went red (25 rows with a tabindex, 50 stops inside the table,
54 before the pagination). Run with `isPreviewPath` returning false: step 5 went red. Step 3: with the Storage settings
wrapped in a `<form>` whose Save button is `type="submit"` and no `holdEnter`, step 3 went red
(`["PUT /v1/settings/storage"]`); the Storage page has no form, so the check can only fail when one is added. Step 7 went red with
`isPreviewPath` returning false (Wiki and Model inventory showed no badge).
