# Run status says what happened

Status: built (2026-10-19), a bug fix from the workflows run review (workflows-run-2, workflows-run-5). Proof:
`make usecase-test UC=uc-249 LAYER=ui ISOLATED=1` (checks 5 to 7).

A run read Succeeded when it ended at a step meant for a failure, and a parent read Succeeded while a run it started
still waited on a person. The status now comes from where the run ended and from the runs it started
(`docs/services/agents-service/overview.md`, A run's status):

- An End has a Counts as setting, Succeeded by default. A run that ends at an End set to Failed reads Failed, and its
  error names that End.
- A run whose own steps finished while a run it started waits on a person reads Waiting, with an alert saying so. It
  succeeds when the last run it started ends.

| Image | What it shows |
|---|---|
| `failed-1280.png`, `failed-400.png` | Before: a lookup that ended at its failure End reads Succeeded. After: Failed, with The run failed naming the End |
| `parent-1280.png`, `parent-400.png` | Before: a parent reads Succeeded while its child waits. After: Waiting, with "Waiting on a run it started" |
| `end-step-1280.png`, `end-step-400.png` | The editor's End step with Counts as (new; there is no before) |
| `runs-list-1280.png`, `runs-list-400.png` | The runs list: the waiting parent, the failed run and the settled runs |

## Review checks (`docs/console/standards.md`)

| # | Result | Evidence |
|---|---|---|
| 1 | Pass | Status, outcome, error and result come from `GET /v1/runs` and `GET /v1/runs/{id}`; Counts as comes from `/v1/workflows/node-types` (End's `result` setting) |
| 2 | Pass | No client changed |
| 3 | Pass | No stub area touched |
| 4 | Not affected | No create screen |
| 5 | Pass | uc-249 #6 reads the alert, #7 the failed run's page and the End's setting |
| 6 | Pass | The alert uses `Alert`, `AlertTitle` and `AlertDescription` with no classes |
| 7 | Pass | No list, chip or clickable div added |
| 8 | Not affected | The page's loading and error states are unchanged |
| 9 | Pass | Every 400 px capture fits: no sideways scroll |
| 10 | Pass | No page or console error while capturing each route at both widths |

A design check in a fresh context passed with fixes, all applied: the alert names the list of runs it started rather than a
row label, the failure line is not repeated, and the End setting is named Counts as with help for both choices. The
choices read in lower case (`succeeded`, `failed`), like every other choice list in the step form. The round N badge in
the corner is the Next.js development indicator, which only shows in development.
