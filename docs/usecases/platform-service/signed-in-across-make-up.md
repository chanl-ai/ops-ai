# A person stays signed in across make up

Status: current. Id: `uc-111`. Service: `platform-service`. Layers: ui.

c-099, owner feedback (smaller-1): the console lost its sign-in on restarts. The cause was `make up` dropping the
whole database whenever any service's migration chain differed from the code, which deleted platform-service's
sessions. `make up` now migrates every chain in place and stops, naming the chain, only when the database is ahead of
the code; only `make reset-db` (or `make up RESET=1`) wipes.

## Preconditions

| Needs | How |
|---|---|
| Docker for compose | the script runs `make up ISOLATED=1 AUTH=platform` itself: ports +1000 (console :4016, platform :9710, agents :9700, PostgreSQL :6477), its own compose project and data volume. Never the shared stack. |
| platform-service's dev seed | James Richardson, builder on Operations; password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James signs in on the isolated console and saves an agent | A session in the browser; the agent saved |
| 2 | kb-service's chain is downgraded one revision, as pulling a commit with a newer migration leaves the database | `schema_sync` reports kb behind and that make up migrates it forward |
| 3 | `make up ISOLATED=1 AUTH=platform` | No drop; every chain at head afterwards |
| 4 | The same browser opens Agents | Still signed in on the same session (`/v1/auth/session` 200); the agent is listed |

`scripts/tests/test_schema_sync.py` covers the check itself: a chain behind is migrated, a chain ahead stops with the
fix named.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `platform-service/scripts/test-uc-111-ui.mjs` | passing |
