# Create a workflow from draft JSON, validate, test, publish and start it

Status: current. Id: `uc-019`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790 (ISOLATED=1 adds 1000) |

The script starts its own agents service on the scripted model; no model key is needed. It turns dev's
`registry_auto_approve` off, so each publish is decided by a second person as it would be outside dev.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `POST /v1/workflows` with the blank template | 201; status `draft` |
| 2 | `PUT /v1/workflows/{id}/draft` with trigger → agent step (`wire-fraud-sentinel`) → review → held or released | 200 |
| 3 | `POST …/validate` with the agent step naming an unknown slug, then `POST …/publish-requests` with it | One failing check; 422 |
| 4 | `POST …/validate` with the real graph | No failing check |
| 5 | `POST …/test` with a sample email | Completes at `held`, one review approved, no thread kept |
| 6 | `POST …/publish-requests` | 201; a `publish_request` review, pending |
| 6a | `POST /v1/publish-requests/{id}/decision` approved, by the requester | 403 |
| 6b | The same, rejected with a reason by a second person; then a new thread | Rejected; 400 `not_published` |
| 6c | A second request, approved by the second person | Approved, with a 64-character digest |
| 7 | `GET /v1/graphs` | Lists the workflow id |
| 8 | `POST /v1/threads {graph: <id>}`, then run it with the email | Pinned to v1; stops at `review` |
| 9 | `GET …/runs` | The run, `waiting_review` |
| 10 | `POST …/validate` on a router with a two-route comparison on `email.subject` and a default | No failing check |
| 11 | The same router comparing `amount` | Fails: unknown field |
| 12 | `POST …/test` on the router with subject `urgent`, then another subject | The review, then the default route |
| 13 | `DELETE /v1/workflows/{id}`, then a new thread | 404 |

The console no longer offers these workflows: the earlier engine left it, so this use case has no ui layer.
The current engine's publish through review is proved in the console by uc-092.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-019-api.py` | passing |

## Non-vacuous check

`the requester cannot approve it (403)` pairs with the second person's approval: removing the requester check fails
the decide test in `test_publish_requests.py`. `an unknown agent fails validation and publish (422)` pairs with the passing validation and publish of the same graph
with a real agent, so the pass is the agent pin's doing. Starting threads on the latest version instead of the
pointer fails the registry test that moves the pointer back to v1.
