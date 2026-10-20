# Create a workflow from draft JSON, validate, test, publish and start it

Status: current. Id: `uc-019`. Service: `agents-service`. Layers: api, ui.

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

In the console (ui layer), with Workflows and Cases pointed at the scripted agents service:

| # | Step | Expected |
|---|---|---|
| 1 | `/workflows`, New workflow, Blank | `POST /v1/workflows` 201, a draft at v0; the editor opens on it |
| 2 | `POST /v1/threads` on its id; the editor header | Refused; no Start run |
| 3 | Test run | `POST …/test` 200, completed, the nodes it reached light up |
| 4 | Add Classify and route, unconnected; publish that draft through the API | 422 `checks_failing`; the publish dialog lists "Every step is reachable" |
| 5 | Delete the node, Publish… with a note | An approved `publish_request`; v1 |
| 6 | Start run from the record with an email | A thread on the workflow id; the run opens in Cases, finished on v1 |
| 7 | A second workflow whose branch has paths Urgent and Other and no default; Publish… | The branch node shows "needs a default route" |
| 8 | In the branch inspector, default Other; Urgent when `email.subject` is "Urgent dispute" | The draft stores `routes.Urgent` and `defaultRoute`; validation passes and the node error clears |
| 9 | Publish, then runs with subject "Urgent dispute" and another subject | The first ends at the Urgent path, the second at the default |

Then a second stack under platform sign-in (James Richardson builder, Maya Okafor approver on team_ops) with
`OPS_REGISTRY_AUTO_APPROVE=false`:

| # | Step | Expected |
|---|---|---|
| 10 | James: Publish… on a new blank workflow | `publish_request` 201, pending |
| 11 | James opens it in Reviews | The approve button reads "Another publisher approves" and is off; his decision through the API is 403 |
| 12 | Maya: Return to requester with no reason, then with one | The form asks for a reason and sends nothing; then 200 `returned` |
| 13 | Read the workflow | Still v0, draft |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-019-api.py` | passing |
| ui | `agents-service/scripts/test-uc-019-ui.mjs` | passing |

## Non-vacuous check

`the requester cannot approve it (403)` pairs with the second person's approval: removing the requester check fails
the decide test in `test_publish_requests.py`. `an unknown agent fails validation and publish (422)` pairs with the passing validation and publish of the same graph
with a real agent, so the pass is the agent pin's doing. Starting threads on the latest version instead of the
pointer fails the registry test that moves the pointer back to v1. At the ui layer, `a draft workflow cannot be
started` pairs with the started run after the console's publish, and the unreachable-step refusal pairs with the publish
that follows deleting that step. James's disabled approve button depends on Reviews matching the signed-in person's
email, which platform-mode requests record: matching by name only leaves the button on and fails step 11.
