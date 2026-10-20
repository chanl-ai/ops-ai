# Builders manage document types, versions, samples and test runs in the console

Status: passing. Id: `uc-243`. Service: `documents-service`. Layers: ui. Card: c-243.

A builder lists the team's document types in Data Hub, opens one, saves a new version from the field table editor,
adds a sample from the team's files with the value it should read, and runs a test that shows its estimate before
anything runs and then matches, misses and accuracy per field. The pages read documents-service; write controls follow
the server's `canCreate` and `canEdit`. The fake model answers what the restraining notice fixtures expect, so this
proves the pages and their calls, not the model's accuracy. The read-only view (a role without `documents.edit`) is not
reachable until RBAC lands: every member holds `documents.edit` (c-256), so it is not driven here.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The fake OpenAI with the documents fixtures' answers | `services/documents-service/tests/fixtures/fake-model/script.json`, through models-service |
| platform-service, files-service and documents-service with the seeded types, and the console, on the run's own ports | started by the script (`withUiStack`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Data Hub > Document types | The seeded types are listed, Restraining notice among them, and New type shows because the list's `canCreate` is true |
| 2 | He opens Restraining notice while its request is slow | The loading state is the page's own skeleton (header, tabs, table), not the record skeleton's side rail; then the fields table shows |
| 3 | New version, set the first field's review threshold to 0.9, save | The editor opens prefilled with every field of the shown version; the picker moves to version n+1, which has the threshold, and version n is unchanged |
| 4 | Samples > Add sample: pick an uploaded restraining notice, enter its case number, add | The sample count goes up by one and the file is listed |
| 5 | Tests > Run test, then Run | The estimate (samples, calls, cost, the 20-sample cap) shows and no test run is requested until Run; after Run the result shows accuracy and the per-field table |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `documents-service/scripts/test-uc-243-ui.mjs` | passing |

## Non-vacuous check

Check 2 fails with the record skeleton back on the type page (`apps/console/src/app/document-types/[id]/page.tsx`):
the record skeleton shows and the page skeleton does not.
