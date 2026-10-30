# Screens open from saved data, and every request shows where its time went

Status: current. Id: `uc-560`. Service: `console` with every service through `ops_service_kit`. Layers: api, ui.
Card: an earlier change.

With `OPS_REQUEST_TIMING=1`, every service writes one JSON line per request on the `ops.request` logger and returns
a `Server-Timing` header with the time spent in the app and in the database. A request id follows the request from the
first service to the next, so their lines can be joined, and an error envelope's `requestId` names the same id. The
console saves what its screens read to the browser, keyed by person, team and app version, and shows it at once on a
reload before refreshing it; Human Tasks and unfinished runs always load fresh, and nothing saved survives sign-out or
a team switch.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | James lists his workflows and the answer says how long the app and the database took, under his own request id | api | 1-2 | 1 |
| S2 | A save that is refused carries one request id through two services and into the error James sees | api | 3 | 3 |
| S3 | Two requests at the same moment each count only their own database time, and with timing off nothing extra is written | api | 4-5 | 4 |
| S4 | James reloads Workflows and his workflow shows at once from what the browser saved, never from another app version | ui | 6-8 | 6 |
| S5 | Signing out, signing out in another tab, or switching team leaves nothing saved | ui | 9-11 | 11 |
| S6 | James changes an agent's name, reloads at once, and sees the new name | ui | 13 | 13 |

## Preconditions

| Needs | How |
|---|---|
| platform-service and agents-service with platform sign-in | `usecase_harness.platform()` and `agents()` with `OPS_AUTH_MODE=platform` |
| Timing on for the first stack, off for the second | `OPS_REQUEST_TIMING=1` in the script's environment; the second platform stack sets it empty |
| James (builder) in team_ops, password `northfield-demo` | The platform seed |
| The use case database | `pg_url()`, for the overlapping requests, which run an app built in the script on the real middleware and engine |
| The console on platform sign-in (ui) | `withUiStack(..., { platform: true })`; Wanjiru (workspace admin) makes Priya a second team |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James lists workflow definitions with his own X-Request-Id | The response returns his id and a Server-Timing with `app` and `db` entries; agents-service logs one line that parses whole as JSON, with route `/v1/workflows/definitions` (the template), status 200, at least one query, team team_ops and his id |
| 2 | He sends a 10 kB X-Request-Id, then one with a space in it | Each is replaced by a minted `req_` id on the response, and neither value appears in the log |
| 3 | He saves a workflow with a Classify step while AI steps are off, with his id | The 422 envelope's requestId is his id; agents-service and platform-service (its `/v1/policies/{key}` read) each log a line with that id |
| 4 | Two requests overlap: one sleeps 0.6 s in SQL, three answer fast with three queries each | The slow line counts one query and at least 500 ms; each fast line counts its own three queries and well under 500 ms |
| 5 | A platform-service with timing off answers a database route | It returns X-Request-Id and no Server-Timing, and logs no JSON line |
| 6 | James opens Workflows, reads it a moment, and reloads with every agents-service read held for 20 s | His workflow's row shows within 12 s, from the browser's saved copy |
| 7 | The saved copy is read from IndexedDB | Every key ends with team_ops; nothing for `me`, `teams`, the sign-in policy, Human Tasks or file preview links |
| 8 | The saved copy is rewritten under another app version, and he reloads | Nothing shows before agents-service answers |
| 9 | He signs out, signs in again and reloads | Nothing is saved after the sign-out, and nothing shows early |
| 10 | He signs out in a second tab | The first tab's saved copy is gone |
| 11 | Priya, in team_ops and a team Wanjiru makes for her, switches team | Nothing of team_ops stays saved |
| 12 | Throughout | No page error |
| 13 | James renames an agent on its page, then at once reloads Agents with every agents-service read held | The old name never shows from the saved copy; the new name shows once agents-service answers |

The non-vacuous checks are step 3 (the id must cross a service boundary, which only `ServiceClient` carries), step 4
(with one shared counter instead of the per-request one, the fast lines would carry the slow query's time), step 6
(the held reads cannot answer inside the window), and steps 9 to 11, which first require a saved copy. The off
switch, NEXT_PUBLIC_OPS_CACHE=off, is proved by `apps/console/src/lib/query-cache.test.ts`: the ui harness builds
the console once per run, so a script cannot flip it.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-560-api.py` | passing |
| ui | `console/scripts/test-uc-560-ui.mjs` | passing |
