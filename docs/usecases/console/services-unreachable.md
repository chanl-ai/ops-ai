# The console says when its services are out of reach, when a session has ended, and when a linked task is gone

Status: current. Id: `uc-404`. Service: `console`. Layers: ui. Card: overview UX run 2026-10-19.

During a database outage every call answered 500 and each page said something different: the overview could not
load, the sidebar said teams were unavailable, and sign-in said something went wrong. The shell now says it once,
with a way to try again. A session that has ended goes back to sign-in, and a link to a task that is gone says so.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and the demo seed | `make db-up`; the use-case stack seeds itself |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya opens Human Tasks from a link to a task that does not exist | A message says the task wasn't found or is closed, and the queue shows without it |
| 2 | Her session is signed out elsewhere, then she opens a page | She is sent to sign-in, with the page she wanted kept as `next` |
| 3 | She signs in again; the run's platform service stops; she reloads | One screen says Ops AI can't reach its services, with Try again; no page or sidebar error shows beside it |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-404-ui.mjs` | passing |
