# Govern > Policies reads and changes the workspace's policies

Status: current. Id: `uc-170`. Service: `console`. Layers: ui.

Card c-178 with c-186: the console's Govern > Policies (`/settings/policies`) lists the workspace policies from
`GET /v1/policies`, one card each with its effect line and its choices, and saves one with `PUT /v1/policies/{key}`.
Whether the person may change them comes from `GET /v1/me/permissions` (settings.manage in the acting team), not from a
role named in the console. Without platform-service the page draws sample policies and says so.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | Sam Adeyemi (Security admin, team_security), James Richardson (builder, team_ops); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam opens Policies | one card per policy (eight), no sample notice, Re-sign-in before deciding is Off (the open default) |
| 2 | He picks On and saves, then reloads | the server answers 200; On after the reload and in `GET /v1/policies`; he puts it back |
| 3 | James opens Policies | "You can't see the policies" with the server's own refusal; `PUT` as James answers 403 |
| 4 | Sam sets the per-team switch Tool writes need approval to On and reloads | 200; On for his team on the server and after the reload; he puts it back |
| 5 | He opens the Publish reviews card | It draws no editor and links to Publish reviews, the one place that setting is changed |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-170-ui.mjs` | passing (5/5) |

## Non-vacuous check

Step 3 goes red if the page swallows the 403 into "request failed". Step 2 is the paired success on the same page.
A person who may read but not change (no such role exists in the seed) gets locked cards from `/v1/me/permissions`.
