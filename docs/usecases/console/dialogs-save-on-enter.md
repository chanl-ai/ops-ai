# A Security admin adds a secret and a host with Enter, and Cancel sends nothing

Status: current. Id: `uc-110`. Service: `console`. Layers: ui.

Card an earlier change: the remaining create and edit dialogs (secrets, egress, tool modules and operations, knowledge pages,
sources, save as template, the thread settings sheet) save on Enter through `DialogShell onSubmit` or their own form.
The integrations revoke dialog is a destructive confirm and keeps an explicit button, so Enter never submits it.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | Sam Adeyemi (admin of team_security); password `northfield-demo` |
| tools-service | the ui stack's tools service, which owns secrets and the egress allow-list |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam opens Add host, types a host and clicks Cancel | no POST reaches tools-service; the host is not listed |
| 2 | He opens Add host again, types it and presses Enter | the host is listed |
| 3 | He opens Add secret, types a name and value and presses Enter in the value | the secret is listed |

## Acceptance layers

| Layer | Script |
|---|---|
| ui | `docs/usecases/console/scripts/test-uc-110-ui.mjs` |
