# c-007 independent review

One entry per commit, by a reviewer that did not build it. Each check ran on a clean `git archive HEAD` export
against a private database (`ops_review_e556`); the working tree was never edited.

## 6bbd7ec: tool-module registry tables, repository and console seed

- Check: tools-service verify 13 passed, inside the green python-verify on the HEAD 3745fcb export. Deleting
  `revision == expected_revision` from `ModuleStore.put` fails test_a_stale_write_is_refused, so that test can fail.
- Spec rule: 007/spec.md:22 and the c-005 answer (005/interview.md:15): tenant_id and team_id from the first
  migration, RLS deferred to c-006.
- Verdict: accept.
- Notes: the four child tables carry tenant_id but not team_id, while 007:22 says "the tables" carry both. That is
  safe while team checks run on the module; record that in the spec or add the column before RLS. Child FKs are
  composite `(tenant_id, module_id)`, so a child cannot point across tenants. The c-005 answer asks for audited
  writes, and module writes are not audited yet.

## c849317: /v1/tool-modules serves the console's tool-module contract

- Check: tools-service verify 13 passed and openapi.json checked, inside the green python-verify.
- Spec rule: 007/spec.md:30 (the requester never decides their own approval); platform-service.md:125, uc-026
  (`X-Dev-User` ignored unless OPS_AUTH_MODE is dev).
- Verdict: reject.
- Defect: `routes.py` `caller()` takes the caller's name from `X-Dev-User` in every environment, and `__main__.py`
  mounts the router whatever `settings.environment` is (only the seed is dev-gated). Outside dev, a requester re-sends
  with `X-Dev-User: <someone else>` and approves their own request. Honour the header only in dev, with a test.
- Gap: done_when (007:9) needs uc-010, and no uc-010 script exists yet (tools-service scripts hold uc-007 and
  uc-015). The commit does not claim it.

---

# c-007 review — second independent reviewer

Reviewer: an independent review session. Checks run on a clean `git archive HEAD` export with isolated databases
and ephemeral ports (the harness picks them).

Gate results on clean export of HEAD:
- `make python-verify`: PASSED (tools 24, agents 201, store 5; openapi 25 ops 3 untyped tools + 61 ops 0 untyped agents)
- `make usecase-test UC=uc-010 LAYER=api`: 10/10 PASSED
- `make usecase-test UC=uc-011 LAYER=api`: 8/8 PASSED

## d0b980b — fix(tools): X-Dev-User names a second person only in dev

| Field | Value |
|---|---|
| check | `make python-verify` + `test_outside_dev_a_header_cannot_change_who_decides[production]` |
| result | PASSED |
| rule | X-Dev-User has no effect in production; a client cannot choose who it is |
| verdict | accept |
| defect | — |

`dev_headers` bool threaded from `__main__` through to `modules_router` and `executions_router`; the `caller`
dependency ignores `X-Dev-User` when `dev_headers=False`. Parametrized test: build app with `dev=False`, request an
approval, attempt to decide it with `X-Dev-User` set to someone else — 403 because the caller is still the fixed
dev user (self-approval refused). Four files, clean.

## 81dea64 — feat(tools): /v1/calls runs registry operations and /v1/executions shows who called

| Field | Value |
|---|---|
| check | `make python-verify` + `make usecase-test UC=uc-010,uc-011 LAYER=api` + 7 new test_calls tests |
| result | PASSED |
| rule | US1+US2: registry is the one source of access class; schema validated before OPA; executors http/stub/local; executions log with caller identity |
| verdict | accept |
| defect | — |

20 files, the largest commit. Key additions:

- **Migration 0003**: adds `module_id`, `latency_ms`, `error`, `approval_token_id` to `gateway_calls`; adds `executor`, `headers`, `body` to `module_operations`; marks revision 0 on unedited seed modules.
- **`executor.py`** (165 lines): `invalid_fields` validates input against the operation's schema (type checks, required, enum, unknown fields refused). `HttpExecutor` calls the module's endpoint with path/body/header templating, egress host allow-list, timeout, 429/400/500 mapping, output masking. `Executor` dispatches by executor type (local/stub/http).
- **`executions.py`** (60 lines): `call_row` maps a raw gateway_calls row to the console's `ToolCallRow` with `subject`/`actor` identity fields from `sub`/`act` principals.
- **`registry.py`** extended: `resolve()` looks up the tool in the module store (when available), returning `Resolved(access, executor, module, operation)`. The registry is the one source of access class — a test asserts every catalogue tool's class matches.
- **`app.py` call route** reworked: resolves through the registry first, runs `_before_policy` checks (hidden operation → 403, unpublished module → 403, schema validation → 422 naming each field) before OPA, then the executor. Every call logs `module_id`, `latency_ms`, `error`, `approval_token_id` (a sha256 fingerprint, never the token).
- **`routes.py`**: new `executions_router` — `GET /v1/executions` with filters (tool, moduleId, thread, decision), paginated, team-scoped.
- **`schemas.py`**: `ToolCallRow`, `CallIdentity`, `CallApproval`, `CallResult`, `ExecutionList` Pydantic models; `ModuleActivity.recent` typed as `list[ToolCallRow]` instead of `list[dict]`.
- **`seed.py`**: `runtime_module` generates a module for locally-run catalogue tools so every callable tool is in the registry. `fields_of` converts JSON Schema to console's SchemaField list. Seed refreshes unedited modules (revision 0), spares edited ones.
- **`store/calls.py`**: `search()` method with filters and total count; `finish()` accepts `**extra` for latency/error.
- **`store/modules.py`**: `put()` gains `seeded` flag (writes revision 0); `operation_named` exists for registry lookup.
- **`fake_upstream.py`**: in-process fake bank API recording every request it receives — tests can assert "nothing left the gateway".
- **`test_calls.py`** (239 lines): 7 tests against OPA + fake bank. Read runs masked and logged with caller. Unknown tool → 403. Hidden operation → 403. Schema failure → 422 before egress (upstream received nothing). Write without token → 403 (with token → 200, logs fingerprint). Upstream failures logged as errors. Egress restricted to module's hosts. Replay with different body is not answered with the first result. Registry and catalogue agree on every access class.
- **`test_registry_store.py`**: new test — changed seed reaches untouched modules, spares edited ones.
- **openapi.json**: +810 lines for the new schemas and routes; `call_v1_calls_post` removed from the untyped allowlist.

## bb357ba — test(tools): uc-010 and uc-011 drive the registry and the gateway end to end

| Field | Value |
|---|---|
| check | `make usecase-test UC=uc-010 LAYER=api` (10 checks) + `make usecase-test UC=uc-011 LAYER=api` (8 checks) |
| result | PASSED |
| rule | done_when: uc-010 and uc-011 passing |
| verdict | accept |
| defect | — |

7 files. uc-010 (68 lines): blank draft 201, literal credential refused 400, vault reference accepted, security review, minor version publish, workflow approval requested 201, self-approval 403, other person approves, restart survives. uc-011 (52 lines): registry read 200 with masked output, write without token 403, missing required field 422, unknown tool 403, all four logged, subject/actor/runId correct, refusals logged as denied. Use-case docs and overview added. Non-vacuous checks documented.

## Probes — adversarial checks

### Probe 1: write without an approval token (403)

Sent `POST /v1/calls` for `update_address` (a write) with no approval token, against tools-service started from
the clean export on port 18720.

```
status: 403
code: gateway_refused
PROBE_1_RESULT: PASSED
```

The registry set `update_address` as a write, OPA demanded a token, and with none provided the call was refused.

### Probe 2: undeclared argument (422 naming it)

Sent `POST /v1/calls` for `get_loan_account` with a valid `loanAccountId` plus an undeclared `extraField`, against
tools-service on port 18721.

```
status: 422
code: invalid_input
invalid: [{'field': 'extraField', 'message': 'Not an input of this operation.'}]
names_the_field: True
PROBE_2_RESULT: PASSED
```

Schema validation caught the undeclared field before OPA and before any egress.

### Probe 3: X-Dev-User has no effect in production

Ran `test_outside_dev_a_header_cannot_change_who_decides[production]` from the clean export against the test
database (`ops_test`), with the app built with `dev=False`. The test requests an approval, then tries to decide it
with `X-Dev-User: Priya Shah`. In production mode the header is ignored, so the requester is deciding their own
request → 403.

```
test_tool_modules_api.py::test_outside_dev_a_header_cannot_change_who_decides[production] PASSED
PROBE_3_RESULT: PASSED
```

## Triage

Three commits reviewed, three adversarial probes run. No defects found.

| Entry | Finding | Verdict |
|---|---|---|
| d0b980b X-Dev-User dev only | accept, no defect | — |
| 81dea64 /v1/calls + /v1/executions | accept, no defect | — |
| bb357ba uc-010 + uc-011 | accept, no defect | — |
| Probe 1: write without token → 403 | gateway refused, no egress | — |
| Probe 2: undeclared argument → 422 | schema caught it, named the field | — |
| Probe 3: X-Dev-User in production | header ignored, self-approval 403 | — |

verdict: approve
