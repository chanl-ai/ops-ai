# A workflow waits for long-running work and carries on when it finishes

Status: current. Id: `uc-525`. Service: `console` on agents-service, documents-service and files-service. Layers: ui. Card: c-525.

A workflow that reads a long file used to wait for the read inside the worker, under a time limit shorter than the
read, so a long document left Extract from file by its error port and the step after it had nothing to decide on.
Now a step that starts long work parks: it holds no worker, and the run carries on when the work reports back, by a
service event or a signed callback, whichever comes first, or by its own Timeout port.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James starts a workflow that reads a six-page tax levy (TAXLEVY01 and five blank pages) | Extract from file parks: the run records `waiting_external` |
| 2 | documents-service finishes the read in the background | It reports `extraction.finished`; the run records `resumed_by_event` |
| 3 | The run carries on | The Decide step branches on the amount the read found; the run succeeds as `large_levy` or `small_levy` |
| 4 | James starts a workflow with a Wait for step | It parks; the run shows a resume URL and token for the outside system |
| 5 | The outside system posts `{"approved": true}` with a forged token, then the real one | 401, then 202; the run ends `approved` |
| 6 | It posts again | 409, already resumed |
| 7 | A Wait for step with a five-second limit gets no answer | It leaves by its Timeout port (`timed_out`); a late callback gets 409 |
| 8 | James opens a waiting run | The page says "Waiting for: Wait for the core system", at 1280 and 400 px |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-525-ui.mjs` | failing |

## Non-vacuous check

Before c-525 every step fails: Extract from file has no Timeout port and `ops.flow.waitFor` does not exist, so neither
workflow saves (`uc-red.txt` under `evidenceDir('525')`).
