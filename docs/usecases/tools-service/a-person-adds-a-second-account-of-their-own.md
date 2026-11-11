# A person adds a second account of their own at their own address and makes it their default

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-702`.
Service: `tools-service` with platform-service. Layers: api, cli. Guide: `docs/guide/plugins.md`, Several accounts of one
app. Design: the several accounts per app design, D3.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A member adds a second account of their own with a name and their own server's address; it signs in there | api | 1 | 1 |
| S2 | Connectors › Mine lists both accounts told apart by their servers | api | 2 | 2 |
| S3 | With two and no default a call asks which; once the second is their default their calls use it | api | 3 | 3 |
| S4 | `opsai apps accounts` shows what each account points at; `opsai apps default APP ACCOUNT --mine` makes it the default | cli | 4 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fake GitHub | `docs/usecases/lib/fake_github.py` (github.test and ghe.corp.test), through `docs/usecases/lib/several_accounts.py` |
| People | Priya Shah (team admin), Maya Okafor (member); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | GitHub on with each person's own account beside the team's; Maya signs in on Platform server, then posts `/v1/me/accounts/{id}/another` with `{name: Corp, settings: {web_url: https://ghe.corp.test}}` and signs in | The sign-in opens at ghe.corp.test |
| 2 | `GET /v1/me/connections` | Platform server (github.test) and Corp (ghe.corp.test) |
| 3 | A call acting for Maya; then Corp pinned as her default; the call again | First ACCOUNT_CHOICE_NEEDED; then the corp server's issue 412 |
| 4 | `opsai apps accounts plugin:opsai.github --as admin`; `opsai apps default plugin:opsai.github corp --mine --as approver` | The rows show their servers; Corp is her default and her call answers issue 412 |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1-3 | With the given address ignored and the first account's copied (`connections/service.py` add_own_account), the sign-in opens at github.test and steps 1-3 fail |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-702-api.py` |
| cli | `docs/usecases/tools-service/scripts/test-uc-702-cli.py` |
