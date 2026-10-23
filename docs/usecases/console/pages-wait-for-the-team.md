# Pages wait for the person's team, and a record in another team says so

Status: current. Id: `uc-505`. Service: `console` with `platform-service` sign-in. Layers: ui. Card: c-505.

Pages used to render as soon as a person was signed in, so their first requests could go out for a team they do not
hold: one remembered in the tab from an earlier sign-in, or the console default. A case opened straight after sign-in
then failed until a reload. The shell now renders pages only once the current team is one of the person's teams, every
query waits for it and is keyed by it (`apps/console/src/hooks/team-query.ts`), and a record that is not in the current
team says "Not found, or in another team" with a team switch.

## Preconditions

| Needs | How |
|---|---|
| A private stack with platform sign-in | `withUiStack(..., { platform: true })` |
| James Richardson, in the Operations team, password `northfield-demo` | The platform seed |
| A case of the Operations team | Step setup opens one through the agents API as James |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The tab remembers `team_security`; James signs in straight to the Operations case | The case shows; no API request answers 4xx or 5xx |
| 2 | James signs in straight to `/cases/case_000000000000` | "Not found, or in another team", with a Switch team menu when he holds another team |
| 3 | A fresh sign-in opens Cases, Runs and Human Tasks | No API request answers 4xx or 5xx |
| 4 | Through all of it | No page error |

Every API request is logged with its team and status to the card's evidence folder (`requests.json`).

The non-vacuous check is step 1: before the gate, the case request went out for `team_security` and answered 404, and
the step failed (the red run is in the card's evidence as `uc-505-red.txt`).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-505-ui.mjs` | passing |
