# Execution-engine conformance suite

Status: done (E9, gaps closed after), 2026-10-11. `services/agents-service/tests/conformance/test_conformance_suite.py`, thirteen tests from
the execution-engine-seam ADR (spec interpreter-and-nodes §9) and the fencing-and-timers ADR, run against the
LangGraph adapter on the scripted model: real PostgreSQL stores and checkpointer, and tools-service in-process with
OPA. No real model calls. Every passing test was seen to fail with its guard removed.

| Spec | Test | Guard removed to watch it fail | What it proved |
|---|---|---|---|
| 2 | `test_crash_after_the_gateway_accepted_a_write_does_not_post_twice` | tools-service dedup claim | A worker killed after the gateway sent a reply resumes and the reply goes out once (`ok` + `replayed`) |
| 3 | `test_the_same_run_key_twice_starts_one_run` | run-id replay in the run route | A repeated run key replays the first run's events; no second run row |
| 4 | `test_an_edit_after_approval_voids_the_old_token` | OPA input-hash rule | An edit after approval re-opens the review, and the old token is refused at the gateway ("issued for a different input") |
| 7 | `test_no_timeout_path_approves` | definition validation on publish | `onTimeout: approve` is refused at publish (400); a reject breach closes the case as rejected |
| 8 | `test_a_customer_reply_restarts_the_sla` | the restart on a customer reply | The old breach timer is cancelled and the new one is not yet due |
| 9 | `test_an_exhausted_retry_budget_lands_in_manual_handling_with_the_error` | the attempt cap | Three failed timeout resumes, then `failed` and `sla.fire_failed` carrying the error |
| 12 | `test_an_agent_interrupt_survives_a_restart_and_resumes_the_same_call` | the pending call key across the interrupt | A new process resumes the approved call under its original key, runs it once, with one model call (the closing answer) |
| 12a | `test_an_agent_retry_after_a_crash_repeats_no_tool_call` | tools-service dedup claim | A worker killed after the resumed turn's tool call is recovered with no second side effect |
| 12a | `test_an_agent_retry_after_a_crash_repeats_no_model_call` | the model-call ledger's lookup | The re-run resume node replays the recorded model response: one model call in all, not two |
| 13 | `test_routing_a_waiting_thread_to_people_raises_the_manual_step` | the route request check | A thread waiting on review goes to the manual step with the reason; its remaining steps are journaled as skipped |
| 13 | `test_routing_to_people_lets_the_write_finish_and_skips_the_rest` | the route request check | A route that arrives while the reply is being sent waits for it: one send, `done` skipped, manual step raised |
| fencing | `test_a_paused_worker_cannot_write_after_takeover` | the checkpointer's fence check | A worker paused past its lease cannot write a checkpoint or the thread status after takeover |
| timers | `test_a_timer_due_during_a_run_fires_once_after_it_or_is_cancelled` | `sync_timers` after the deciding run | A timer due mid-run is `busy`, then fires once (`fired`, then `duplicate`), or is `cancelled` if the run decided |

Both earlier gaps are closed: R9 (`ops_agents/api/routing.py`, `POST /v1/threads/{id}/route-to-people` and `POST /v1/threads:route-to-people`) and a model-call ledger (`ops_agents/api/model_ledger.py`, table `model_calls`).

## Gotchas

| Topic | Detail |
|---|---|
| Bug found | LangGraph's task stream reports a task that raised with a `result` key too, so `runs.execute` emitted `node_end` for a failed step and a timeout fire counted it as accepted. `node_end` now carries `error`, and `fire` accepts only a clean one. This was caught by spec 9 |
| A vacuous first draft | The retry-budget test first read `MAX_ATTEMPTS` from the code under test, so raising the cap moved the expectation with it. It now pins the ADR's three attempts |
| Edits are writes | On a fenced thread a state edit needs the lease and its generation. A bare `update_state` moves the graph past its interrupt, so an edit must re-run the thread to the review |
| A tool exception is not a crash | The kernel turns a tool exception into a tool error for the model. Crash tests kill the node after the turn instead |
| Shared database | The shared database runs ahead of HEAD when another session's migration is applied. Verify on a scratch database, migrated first |
| R9 stops at step ends | The route flag is read only when a step ends with no write step in flight, so a write always finishes; closing the stream then cancels in-flight reads. Code graphs have no plan to skip and refuse with 409. The publisher role is not checked: dev auth has no roles, so the requester is recorded instead |
| Ledger key | Responses are keyed by thread and a hash of the request without timestamps and run ids, recorded only after the stream is read to the end. It lives outside the kernel for now; the kernel's step ledger is where it belongs |

## Feeds

| Into | What |
|---|---|
| execution-engine-seam ADR | The suite every engine adapter must pass. DBOS and Temporal spikes run it unchanged |
| Kernel | Move the model-call ledger into the kernel's step ledger |
| Auth | A publisher role for the route-to-people routes |
