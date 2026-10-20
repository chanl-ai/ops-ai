# A levy notice from the mailbox becomes customer cases a reviewer holds or flags

Status: retired 2026-10-18 (c-212): the v1 levy flow and its mailbox deployment are gone; uc-210 (`levy-on-the-runner.md`) covers the levy notice on the workflow runner. Kept as the record of what the v1 flow did. Id: `uc-076`. Service: `agents-service`. Layers: api. Card: c-057 (T006).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| agents-service on the scripted model, with tools-service as its gateway and the fake Graph source | started by the script on the run's own ports (`OPS_MAILBOX_SOURCE=fake`, the seeded `dep_levy_mailbox` deployment) |
| The bank system on https | the scripts' fake bank (`services/tools-service/scripts/fake_bank`), served by the script, listed on egress with its private range, imported as a published module with `place_hold` approved by one person of `team_ops` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Drop the fixture notice (`tests/fixtures/mailbox/levy_notice.json`, a text PDF naming three persons) and poll | one `levy-intake` thread; three records; two matches (Marcus Bell by name and address, Priya Natarajan by name and the last four); Jordan Whitfield a candidate on the parent, no case; two `levy-case` threads offering hold and flag |
| 2 | Maya decides Hold with amount 1500 on Marcus's case | 200; the case ends `held` with the bank's `HLD-` id; the bank holds 1500 on CHQ-2219; the gateway logged one allowed hold on Maya's approval |
| 3 | Maya decides Flag on Priya's case | 200; the case ends `flagged`; the bank holds the note; the parent lists both outcomes |
| 4 | Drop the same notice again and poll | no new thread, one duplicate |
| 5 | A second notice (new Message-ID); Maya holds 9000 on Marcus's new case | the bank answers 422; the case shows status 422 in `tool_error` and on the review; it waits for a new decision; the bank holds only the first hold |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-076-api.py` | passing |

## Non-vacuous check

Step 1's candidate check fails when a name alone counts as a match (`record_matches`, `tests/api/test_levy.py::test_a_name_alone_is_never_a_match`, seen failing with the address and SSN clauses removed). Step 5 fails when a failed hold is retried or ends the case: `test_a_hold_over_the_balance_shows_the_422_and_waits_for_a_new_decision` counts the bank calls and was seen failing with the outcome condition routed to `held`.
