# A court order notice's cases are decided from the console

Status: retired 2026-10-18: it read the v1 court order run in Cases; the v1 flow is gone. uc-210 decides v2 court order cases through the API, and the console view of them belongs to the Cases card. Id: `uc-077`. Service: `console`. Layers: ui. Card: an earlier change (T009).

As Maya (reviewer, team_ops), the intake run of a court order notice shows the persons it names, the candidates a person
reads and the cases it opened; each case is decided in Reviews with Hold (an amount) or Flag; the hold id lands on the
case and Activity lists the call behind it.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and Docker (for OPA) | `make db-up`; the harness starts its own OPA container |
| platform-service, tools-service with the https core-banking fake bank (`OPS_FAKE_BANK_APP=core`), agents-service on the scripted model with tools-service as its gateway and the fake Graph source | started by the script on the run's own ports (`withUiStack` with `platform`, `tools.bank`, `tools.gateway`; `OPS_MAILBOX_SOURCE=fake`, the seeded `dep_levy_mailbox` deployment) |
| The bank as a published module | imported by the script over the API: reads from GET, `place_hold` approved by one person of `team_ops` with a step-up, published by Security |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Allow the bank on egress, store its key, import and publish the module | `published` |
| 2 | Drop the fixture notice into the fake mailbox and poll as Maya | one `levy-intake` thread; two `levy-case` threads, one for CUS-1001 (Marcus Bell) and one for CUS-1002 (Priya Natarajan) |
| 3 | Open the intake run in Cases | the sheet lists the three persons, Jordan Whitfield as a candidate, two child cases; the trace shows three Match steps |
| 4 | Open Marcus's review; the hold's declared amount reads 3250; hold 1500 | the console asks Maya to confirm it is her (the hold's policy asks for a step-up with one approver); 200; the case ends `held` with a `HLD-` id and the approved call's amount 1500 |
| 5 | Open Marcus's case; follow Tool calls behind this run | the outcome shows the hold id; Activity opens filtered on the case and lists `place_hold` |
| 6 | Open Priya's review; Flag | no step-up; 200; the case ends `flagged` with the note's id |
| 7 | Open the intake run again; follow List them in Cases | each child row says held or flagged; Cases filtered by the parent (`?parent=`) lists both child cases under Done today |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-077-ui.mjs` | passing |

## Non-vacuous check

Step 4 pairs the decision with the state the service holds afterwards: the hold id and the approved call's amount come
from `GET /v1/threads/{id}/state`, not from the page, so a form that posts the wrong amount or an option the server
refuses fails it; it also requires the step-up dialog to have appeared, and step 6 requires it not to, so a console
that asks for every option or for none fails one of the two. Step 5 fails when the Activity link opens the log
unfiltered or the gateway logged no call for the case thread.
