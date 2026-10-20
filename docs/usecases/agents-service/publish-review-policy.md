# An admin decides which publishes need a review: never publishes at once, always opens a review, a builder cannot change it

Status: passing. Id: `uc-114`. Service: `agents-service`. Layers: ui. Card: c-086 (T008).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| platform-service with the dev seed: Priya admin and James builder of team_ops | `withUiStack({ platform: true })` |
| Dev auto-approve off, so "major changes only" is the rule a test can tell apart from "never" | `OPS_REGISTRY_AUTO_APPROVE=false` on the run's agents service |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Govern > Policies > Publish reviews | every area shows "Review major changes", Tool modules included (tools-service obeys it since c-214), and the selects are disabled; `PUT /v1/policies/publishReview` as James answers 403 |
| 2 | As James, change an agent's role (a minor field) and request a publish | approved at once; the request records `policy: major`, `majorChange: false` |
| 3 | Priya sets Agents to Publish at once and saves | "Saved publish reviews"; the page shows it (a team admin cannot read policies, so it shows what the save returned) and the server holds `never` for team_ops |
| 4 | James changes the agent's instructions (a major field) and requests a publish | approved at once with `policy: never`, `majorChange: true` |
| 4a | James publishes a new draft from the agent page (c-139) | the page says "Published {name} v{n}" with no review link |
| 5 | Priya sets Agents to Review every change and saves | the server holds `always` for team_ops |
| 6 | James changes the role again and requests a publish | the request is pending with `reviewRequired: true`, `policy: always` |
| 6a | Priya rejects that request; James publishes a new draft from the agent page | the page says "Sent {name} v{n} for review" with Open review |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-114-ui.mjs` | passing |

The publishes in steps 2, 4 and 6 go through the API as James, since the agent page's publish button calls the same
route; the settings changes go through the page.

## Non-vacuous check

Step 6 fails when the "always" rule is ignored, because a minor change is otherwise approved at once (step 2 shows
that it is). Seen failing once with `always` decided as `major` in `api/publish_policy.py`: step 6 reported
`review: approved, reviewRequired: false, policy: always` and the run exited 1; the other seven checks passed. Step 1
fails if a builder can save; that rule is watched failing in `tests/api/test_publish_policy.py`. Step 4a fails when
the agent page words every result as a review: with its `live` forced false the page said "Sent Branch Concierge v6
for review" and the run exited 1.
