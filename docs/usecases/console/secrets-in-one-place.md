# A Security admin manages every secret in one place

Status: current. Id: `uc-107`. Service: `console`. Layers: ui.

c-093: secrets management and connectivity with tools. Settings > Secrets shows each
tool secret with the operations that read it, rotates it for all of them at once, refuses a delete while one reads it,
limits it to teams the gateway enforces, and lists the storage credentials files-service keeps beside them.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | Sam Adeyemi (Security admin), James Richardson (builder, Operations), Nadia Petrov (approver); password `northfield-demo` |
| The fake core bank on https | the ui harness with `tools: { bank: 'core' }`; its statement route takes its key in the query string |
| A published module | set up through the API: two operations read `{{STMT_KEY_<tag>}}`, which holds a wrong value at first |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam opens Settings > Secrets and finds the secret, which five operations read | three operation chips, each linked to its workbench, then "and 2 more" with the rest in its tooltip; the Storage credentials section is there |
| 1b | He reloads the page while the storage credentials answer slowly | skeleton rows show while they load, not a line of text |
| 2 | Sam opens the row's menu | Delete is off with "Read by 5 operations" as the reason; tools-service refuses the delete with 409 |
| 3 | James runs one operation live; Sam rotates the secret to the bank's key; James runs both | 401 before; both 200 after; no response carries the key |
| 4 | Sam opens Change teams, where the teams are one labelled group; a save that fails shows in the dialog; he saves again, limiting the secret to Security; James runs live | the error shows as an alert inside the dialog; then refused with SECRET_OUT_OF_SCOPE, and the workbench says the secret is not available to the module's team |

`services/tools-service/tests/test_secret_usage.py` covers the same rules per failure mode, including a name made
before the 64-character rule.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-107-ui.mjs` | passing |
