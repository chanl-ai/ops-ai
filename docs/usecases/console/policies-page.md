# Govern > Policies reads and changes the workspace's policies

Status: current. Id: `uc-170`. Service: `console`. Layers: ui.

The console's Govern > Policies (`/settings/policies`) lists the workspace policies from
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
| 6 | He opens Apps whose writes need approval, searches for an app that is not there, then picks the team's first app by part of its name and saves | No app listed by default; the search is read from `GET /v1/systems` and an empty one says No app matches; 200, and the app's id is listed for his team on the server and after the reload |
| 7 | In that picker, with the search empty | Mailboxes is offered: the built-in apps stay pickable here (`GET /v1/systems?include=builtin`), though the Apps grid leaves them out |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-170-ui.mjs` | failing one check (2026-11-03), 9 of 10: the apps card shows no "No app listed" line (the names card never draws `defaultLabel`, `apps/console/src/app/settings/policies/page.tsx:55`), and after a reload the picked app reads as its id, `builtin:document-types`; the picker's `GET /v1/apps` read answers 200 |

## Non-vacuous check

Step 3 goes red if the page swallows the 403 into "request failed". Step 2 is the paired success on the same page.
A person who may read but not change (no such role exists in the seed) gets locked cards from `/v1/me/permissions`.
