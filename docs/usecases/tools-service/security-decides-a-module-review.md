# Security decides a tool module review

Status: current. Id: `uc-040`. Service: `tools-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder, Operations), Maya Okafor (approver, Operations), Nadia Petrov (approver, Security); password `northfield-demo` |
| tools-service verifying platform tokens | The scripts start it with `OPS_AUTH_MODE=platform` (the ui harness does when `platform` is on) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James creates a module with one operation and requests a security review | 201 / 200; the review is pending |
| 2 | Nadia lists `view=security_review` | the module, with `pendingReview.requestedBy` James Richardson |
| 3 | James decides his own review | 403 |
| 4 | Maya (approver on Operations) decides it | 403, naming the Security team |
| 5 | Nadia requests changes with no finding | 400 |
| 6 | Nadia approves | 200, the module is published, and it leaves the view |
| 7 | On a second module Nadia requests changes with a reason | 200, back to draft, the reason in the review's findings |

In the console (ui layer): James's Approval tab shows the decision form off ("Security decides"); Maya sees the module
in Reviews > Tool modules with the form off, and the service refuses her; Nadia's change request without a reason is
stopped in the form and sends nothing, then she approves from the tab, the row leaves it, and the module page shows
the review approved by her; the publish dialog says "What changed" is required.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-040-api.py` | passing |
| ui | `tools-service/scripts/test-uc-040-ui.mjs` | passing |

## Non-vacuous check

Step 4 pairs with step 6: removing the Security-team rule lets Maya's decision through (200). Tokens from platform's
dev sign-in carry `auth_method: dev`; a rule keyed on that alone would also let Maya through, which is the bug the api
layer caught (74f78f2). At the ui layer, the stopped change request pairs with the approval that follows.
