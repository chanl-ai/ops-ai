# The workspace name and the tool list come from the services

Status: current. Id: `uc-232`. Service: `console` on platform-service and agents-service. Layers: ui.

Pages that are live must not show sample data. The sidebar's team switcher names the workspace from platform-service
under the team, the header does not repeat either, and the Tools page's workflow tools are agents-service's directory, not the console's mock.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James signs in and reads the sidebar's team switcher and the header | The switcher shows Operations over platform-service's `tenantName` from `/v1/me` and Ops AI, with no sample environment; the header names neither |
| 2 | He opens Tools › Workflows | The rows are the workflow tools `GET /v1/tools?kind=workflow` lists |
| 3 | The workspace admin names the workspace Harbor & Pine Bank through `PATCH /v1/settings/workspace`; James tries the same | The admin's rename is saved and James is refused (403); James's sidebar shows Harbor & Pine Bank after a reload |
| 4 | James opens Settings › Workspace; Wanjiru opens it, renames the workspace and saves | James sees the name locked; Wanjiru's save answers 200 and her sidebar shows the new name |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-232-ui.mjs` | passing |
