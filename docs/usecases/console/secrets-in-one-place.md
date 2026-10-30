# A team manages its own secrets in one place

Status: current. Id: `uc-107`. Service: `console`. Layers: ui.

an earlier change: secrets management and connectivity with tools; an earlier change: a secret belongs to one team. Settings > Secrets shows
the current team's secrets with the operations that read each, rotates one for all of them at once, refuses a delete
while one reads it, and lists the storage credentials files-service keeps beside them. Another team that calls the same
system keeps its own secret under the same name.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder, Operations), Sam Adeyemi (Security admin), Nadia Petrov (approver); password `northfield-demo` |
| The fake core bank on https | the ui harness with `tools: { bank: 'core' }`; its statement route takes its key in the query string |
| A published Operations module | set up through the API: five operations read `{{STMT_KEY_<tag>}}`, Operations' secret, which holds a wrong value at first |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Settings > Secrets in Operations and finds the secret, which five operations read | three operation chips, each linked to its workbench, then "and 2 more" with the rest in its tooltip |
| 1b | Sam, in Security, opens the page while the storage credentials answer slowly | the Storage credentials section shows skeleton rows while they load, not a line of text |
| 2 | James opens the row's menu | Delete is off with "Read by 5 operations" as the reason; tools-service refuses the delete with 409 |
| 3 | James runs one operation live, rotates the secret to the bank's key, and runs both | 401 before; both 200 after; no response carries the key |
| 4 | Sam searches for the key in Security, then adds a secret under the same name there | Operations' secret is not listed for him; the dialog says the secret is saved in Security and has no teams picker; it is created (201); James's row is still at v2, his run still answers 200, and his row menu offers no teams change |

`services/tools-service/tests/test_secret_usage.py` covers the same rules per failure mode, including a name made
before the 64-character rule.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-107-ui.mjs` | passing |
