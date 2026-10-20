# A changed publish review setting applies to the next tool module publish

Status: current. Id: `uc-137`. Service: `console`, `tools-service` and `platform-service`. Layers: ui.

Which publishes need a second person is the team's publishReview setting (Settings, Policies, Publish reviews). A change
used to reach a publish only after a token refresh or a restart; tools-service and agents-service now read it on every
publish (c-214), so an admin's change applies to the very next one.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents, tools, platform-service and console (ISOLATED=1 adds 1000) |

Priya is Operations' admin; James builds there. James's module has one published version, set up through the API, and
each step stages a minor change (a new operation description) before he publishes.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya sets Tool modules to Publish at once and saves; James publishes the module's change | The save answers 200; the publish says "Published …" |
| 2 | Priya sets Tool modules to Review every change and saves; James publishes the next change | The save answers 200; the publish says "Sent … for review", with no restart between |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-137-ui.mjs` | passing |
