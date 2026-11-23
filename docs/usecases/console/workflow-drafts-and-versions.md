# A builder edits a workflow that saves itself, publishes it past its problems and compares its versions

Status: current. Id: `uc-761`. Service: `console`. Layers: ui.

The workflow editor saves a working copy a second after each change and makes no version until Publish. The header
says where the save stands and how many problems remain; leaving with a change not yet saved asks first. A second
person's save made on an older copy is refused with who saved first. Publish lists what changed and every problem
that stops it, and sends nothing while one remains; a change of step positions alone goes live with no review. The
Versions tab compares two versions setting by setting and restores one as the working copy. A viewer sees the canvas
with no save state and no Publish.

## Preconditions

| Needs | How |
|---|---|
| A stack with platform sign-in and publish review on for workflows (`major`) | the ui harness with `platform: true` and `OPS_REGISTRY_AUTO_APPROVE=false`; `publishReviewOn({ workflows: 'major' })` |
| A live three-step workflow | James saves it through `POST /v1/workflows/definitions` and asks to publish; Maya approves |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens the workflow | No Save version button; Save is disabled; the save state reads "Saved" and nothing was sent; the problems chip reads "No problems" |
| 2 | James changes a step's settings | "Saving…" then "Saved"; `PUT …/working-copy` was sent and the workflow still has one version |
| 3 | James breaks a step | The chip counts the problem ("1 problem"); the copy still saved |
| 4 | James presses Back before the save lands | "Discard changes?" asks; Keep editing stays |
| 5 | James opens Publish with the problem | The problem is listed with Fix; pressing Publish sends nothing and the workflow keeps one version |
| 6 | Another builder saves on the copy James read, through the API | Refused with `stale_base`, naming James |
| 7 | James fixes the step and publishes | The dialog lists the changed step; the publish waits for review ("In review") |
| 8 | James moves a step only and opens Publish | The dialog says it goes live at once; publishing makes it live with no review |
| 9 | James opens Versions and compares | Each version is listed; Compare shows the changed setting old and new |
| 10 | James restores version 1 | The working copy holds version 1's steps; no version is added |
| 11 | Ravi, a viewer, opens the workflow | The canvas shows; no save state, no Publish |
| 12 | Screens at 1440 and 390 | Canvas with the save state, the publish dialog and the Versions tab |

## Scripts

| Layer | Script |
|---|---|
| ui | `scripts/test-uc-761-ui.mjs` |
