# c-009 verify evidence

`codeloop verify c-009` on the shared tree; the use cases are in `usecases/009/`, one per acceptance line.

result: pass
sha: bfb69723f9a52f444627047a8f9dec40af068bb8
env: local

| Use case | Accepts | Layers |
|---|---|---|
| us1-models-service-streams-tools-and-refusals | US1 | cli pass |
| us2-an-agent-runs-on-its-alias | US2 | cli pass |
| us3-a-refusal-reaches-the-caller | US3 | cli pass |

## Clean-export run

Status: current. Runs on a clean export of `fc3f960` (no uncommitted files from any session), 2026-10-11, with
`make db-up` running and a fresh test database. Commands are the card's verification block. Use cases run with their
own database and ports, because `ops_usecase` and 8790-8792 are shared with every session:
`UC="OPS_USECASE_DB=ops_usecase_c009 OPS_USECASE_AGENTS_PORT=8890 OPS_USECASE_TOOLS_PORT=8891 OPS_USECASE_MODELS_PORT=8892 OPS_USECASE_CONSOLE_PORT=3118"`.

| Command | Expected | Result |
|---|---|---|
| `make python-verify` | exit 0; models-service 21 tests, 13 operations, 0 untyped; agents-service 201 tests, 61 operations, 0 untyped | exit 0; models-service `21 passed`, `openapi: 13 operations, 0 untyped on the allowlist`; agents-service `201 passed`, `check_standards: 190 files, 0 problems`, `openapi: 61 operations, 0 untyped on the allowlist` |
| `make usecase-test UC=uc-028 LAYER=api $UC` | 8 checks | `PASS uc-028 api 8 checks passed` |
| `make usecase-test UC=uc-018 LAYER=api $UC` | 13 checks | `PASS uc-018 api 13 checks passed` |
| `make usecase-test UC=uc-019 LAYER=api $UC` | 18 checks | `PASS uc-019 api 18 checks passed` |
| `make usecase-test UC=uc-020 LAYER=api $UC` | 9 checks | `PASS uc-020 api 9 checks passed` |

Real model calls: 10, all in the E13 baseline (2c89ed7), owner-approved, about $0.01. Every other run above used the
scripted provider; uc-028 checks that every call it made went to a `scripted-*` provider model.

Non-vacuous checks seen failing with their guard removed, during build:

| Task | Guard | Test | Failure seen |
|---|---|---|---|
| T001 | `tool_calls` passed through (scripted stream, scripted JSON, openai-compatible) | `test_a_tool_turn_carries_the_tool_call_and_its_result`, `test_an_openai_compatible_provider_gets_the_tools_and_returns_the_calls` | `assert [] == ['lookup_case']` in each of the three paths |
| T002 | `X-Request-Hash` kept on the call log | `test_a_call_carries_the_callers_request_hash_and_is_found_by_thread` | `assert [(..., None)] == [(..., 'aaaa…')]` |
| T003 | Responses match the documented models | every models-service test, through the contract hook | `keys_list_keys 200 does not match its schema at data/0: Additional properties are not allowed ('drift' was unexpected)` |
| T004 | `max_retries=0` on the client | `test_a_refusal_reaches_the_client_once` | `assert ['denied', 'denied', 'denied', 'ok'] == ['denied', 'ok']` |
| T005 | The kernel asks the source for the turn's alias | `test_a_turn_runs_on_its_agents_alias` | `assert 'ran on the runtime model' == 'ran on bank-reasoning'` |
| T005 | `max_retries=0` in `ModelsServiceModels` | `test_the_models_service_source_sends_one_request_per_refusal` | `assert 3 == 1` |
| T006 | Per-alias source in agents-service | `test_an_agents_turn_runs_on_its_alias_with_this_services_key` | the turn answered `Answered on bank-standard.` |
| T006 | Call headers from `LedgerModel` | `test_a_graph_runs_record_and_models_service_name_the_same_alias_and_request` | `KeyError: 'x-thread-id'` |
| T007 | The kernel keeps a refusal's status and code | `test_a_refusal_answers_the_test_turn_with_its_status_and_code` (4 cases), the stream test | all five failed: 200 instead of the refusal |
| T007 | The error frame carries the code | `test_a_refusal_ends_a_streamed_turn_with_its_code_and_a_reload_keeps_it` | `assert ('error', None) == ('error', 'rate_limited')` |
| T008 | Replay from the record | `test_a_rerun_of_the_same_task_is_answered_from_the_record_not_models_service` | `assert 2 == 1` (models-service called twice) |
| Picker | Chat aliases only | `test_the_alias_picker_lists_exactly_what_publish_accepts` | `assert ['bank-standard', 'bank-embed'] == ['bank-standard']` |
| Fix | The usage chunk on a scripted stream | `test_a_text_turn_runs_through_the_openai_client[True]` | `assert (0, 0) == (3, 4)` |
| Fix | Settled before `[DONE]` | uc-028 | 2 of 3 runs failed: models-service answered `connection is closed` on the call-log read |
| T009 | Per-alias source, end to end | uc-028 | checks 1, 2 and 4 FAIL: `scripted reply from scripted-standard`, no call-log row, empty log for the thread |

The card's fourteen commits: a5082ec, 3903988, c466de8, 0e9e827, d2efdd6, c3f951b, 081e5dd, ba2828b, c1f4a85,
9e71c14, c1d1095, f23d68f, 2c89ed7, fc3f960.
