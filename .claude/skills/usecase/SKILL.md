---
name: usecase
description: Use case testing for Ops AI at the API, SDK, CLI and UI layers. Use when running, writing, reviewing or checking coverage of a use case (docs/usecases/), when asked to prove a backend or console change end to end, or when the user types /usecase list|show|test|new|coverage.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# /usecase

Use cases in `docs/usecases/` are the central end-to-end check: one script per use case and layer, driving only what
a client can drive. Unit and integration tests stay with each service (pytest in the Python services). The runner is
`packages/usecase-runner`, called through `make` (`scripts/usecase.mjs` underneath). Registry, rules and layout:
`docs/usecases/README.md`.

## Routes

| Route | Run | Then |
|---|---|---|
| `list` | `make usecase-list` | Show the table as printed |
| `show <id>` | `make usecase-show UC=<id>` | Open the use case doc; say which layers have scripts |
| `test UC=<id> [LAYER=api\|sdk\|cli\|ui]` | `make usecase-test UC=<id> LAYER=<layer>` (needs `make db-up`) | Paste the PASS/FAIL lines and the summary line. A failure is reported with its output, never explained away |
| `new <service> "<title>"` | `make usecase-new SERVICE=<service> TITLE="<title>"` | Fill the doc (preconditions, steps and expected results, non-vacuous check; no narrative), write the api script, run it, set the registry status from what the run printed |
| `coverage <service>` | `make usecase-coverage SERVICE=<service>` | Report missing required scripts first, then layers not available yet |

## Layers

| Layer | Script | Available |
|---|---|---|
| api | `test-uc-NNN-api.py`: httpx against services started by `docs/usecases/lib/usecase_harness.py` | Always |
| sdk | `test-uc-NNN-sdk.py` or `.mjs` on the generated SDK | Once `packages/sdk-py` or `packages/sdk-ts` exists; until then the runner prints "sdk not available yet; run LAYER=api" and exits 3 |
| cli | `test-uc-NNN-cli.*` driving the `ops` CLI | Once `packages/ops-cli` exists; same fallback |
| ui | `test-uc-NNN-ui.mjs`: Playwright headless via `withUiStack` from `@ops-ai/usecase-runner/harness` | Always (the console) |

## Hard rules

1. **Scripted model only.** Scripts start the agents service with `services/agents-service/scripts/scripted_server.py`
   (the test suite's scripted model and fake workflow models) on the use-case ports, never the `make up` stack on
   :8700. The runner removes `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. Real model calls are forbidden unless the owner
   approved a count and the run sets `APPROVED_REAL_CALLS=<n>`; ask before setting it.
2. **A pass needs evidence.** A script prints one `PASS <name>` or `FAIL <name>: <detail>` per check through the
   harness `check()` and ends with `finish()`. The runner passes it only on exit 0, no FAIL line and at least one PASS.
   Do not print PASS by hand or catch a failure to keep a script green.
3. **Name the non-vacuous check.** Every doc has a "Non-vacuous check" section naming the check that fails when the
   behaviour breaks; prefer a refusal paired with the success it guards (uc-002: approve without step-up is 422, then
   with step-up is 200). Before marking a new use case passing, break the behaviour once (or point the script at a
   case that must fail), watch that check go red, restore, and say what you broke.
4. **The registry status is not evidence.** Only a `make usecase-test` run in this session decides what passes.
5. **Never reuse a port someone else holds.** The harness refuses a busy port; stop your own leftover process or use
   `ISOLATED=1`. Do not kill the shared stack's processes.
6. **Assert values, not existence.** Check the id, the amount, the status code, the count, not that a field is present.

## Writing a script

```python
from usecase_harness import TEAM, agents, check, data, finish   # also: tools, new_thread, run, state, nodes, sse, EMAILS

with agents() as api:                     # agents service on the scripted model, its own migrated database
    res = api.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]}, headers=TEAM)
    check("thread created (201)", res.status_code == 201, res.text[:200])
finish()
```

The scripted model answers by keyword (`services/agents-service/tests/conftest.py`): a question with "limit" over
knowledge cites `doc_wire_limits`; a `W-<n>` wire id calls `place_wire_hold`; `CHQ-` calls `lookup_account`. A use
case that needs another reply extends that script in the service, with a unit test, rather than calling a provider.
