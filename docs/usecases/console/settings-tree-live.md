# The live settings follow the approved tree

Status: current. Id: `uc-152`. Service: `console`. Layers: ui.

Card c-178 (build): the settings mock was approved (`settings-tree-mock.md`, uc-126). The real pages move to its
tree a page at a time. Inside settings the app sidebar is replaced by the settings sidebar (back arrow, Find, Workspace,
Team and Govern groups, My account at the foot); a moved page answers at its new route and its old route redirects.
Policies stay on their current page until `GET` and `PUT /v1/policies` exist (c-186).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | Sam Adeyemi (Security admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam opens Webhooks | the app sidebar is gone; the settings sidebar shows a back arrow, Find, Workspace, Team, Govern and My account, and no role switch |
| 2 | He presses F, types "storage" and picks the result | Find has focus; Storage opens |
| 3 | He opens Secrets | the header names it and holds Add secret, once |
| 4 | He opens each moved page by its old route | it lands on the new route |

## Moved so far

| Old route | New route |
|---|---|
| `/settings/publish-reviews` | `/settings/policies/publish-reviews` |
| `/reviews/policies` | `/settings/policies/gates` |
| `/settings/general` | `/settings/team` |
| `/account/security` | `/settings/account/security` |
| `/account` | `/settings/account` |
| `/settings/usage` | `/settings/workspace/usage` |
| `/settings/secrets` | `/settings/security/secrets` |
| `/settings/egress` | `/settings/security/egress` |
| `/settings/sign-in` | `/settings/security/sign-in` |
| `/settings/notifications` | `/settings/team/notifications` |
| `/settings/webhooks` | `/settings/team/webhooks` |
| `/settings/api-keys` | `/settings/team/api-keys` |
| `/settings/storage` | `/settings/workspace/storage` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-152-ui.mjs` | not run |

## Non-vacuous check

Step 1 goes red when the shell keeps the app sidebar on `/settings` routes. Step 4 goes red for any page whose old route
renders it instead of redirecting.
