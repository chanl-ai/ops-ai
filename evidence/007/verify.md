<!-- codeloop verify: start -->
# Verify c-007

result: pass
sha: 221f7d5139aa53d145ebb7e9166c0fae6694075a
env: local

| Use case | Accepts | Layers |
|---|---|---|
| us1-a-builder-manages-a-tool-module | US1 | cli pass |
| us2-every-call-runs-through-the-registry | US2 | cli pass |
<!-- codeloop verify: end -->

# Verify c-007

result: pass
sha: ece248d7ec9ea76f8fc9a702c25d92373a2eb66d
env: local

| Use case | Accepts | Layers |
|---|---|---|
| us1-a-builder-manages-a-tool-module | US1 | cli pass |
| us2-every-call-runs-through-the-registry | US2 | cli pass |

## Runs on a clean checkout

Status: current. Runs on a clean worktree of `bb357ba` (no uncommitted files from any session), 2026-10-11, with
`make db-up` running. Commands are the card's verification block.

| Command | Expected | Result |
|---|---|---|
| `make usecase-test UC=uc-010 LAYER=api` | 10 checks | `PASS uc-010 api 10 checks passed` |
| `make usecase-test UC=uc-011 LAYER=api` | 8 checks | `PASS uc-011 api 8 checks passed` |
| `make usecase-test UC=uc-007 LAYER=api` | 4 checks | `PASS uc-007 api 4 checks passed` |
| `make usecase-test UC=uc-027 LAYER=api` | 6 checks | `PASS uc-027 api 6 checks passed` |
| `make -C services/tools-service verify` | lint, pyright, 24 tests, OpenAPI gate | `All checks passed!`, `0 errors`, `24 passed`, `openapi: 25 operations, 3 untyped on the allowlist` |
| `make -C services/tools-service test-gateway` | 37 tests | `37 passed` |
| `make verify` | exit 0 | exit 2: platform-service's tests stop with `Can't locate revision identified by '0002_tenant_fks'` before tools-service and agents-service run |

The `make verify` failure is outside this card: platform-service's committed tests (3745fcb) reach a database that
another session migrated with an uncommitted revision, and they fail the same way on HEAD without any c-007
change. Every suite this card touches passes on its own, as the rows above show; the gate needs rerunning once the
platform revision is committed or the database is reset.

Non-vacuous checks seen failing with their guard removed, during build:

| Guard | Test | Failure seen |
|---|---|---|
| Revision check on module writes | `test_a_stale_write_is_refused` | `DID NOT RAISE StaleModuleError` |
| Requester never decides | `test_the_requester_never_decides_their_own_approval` | `assert 200 == 403` |
| X-Dev-User only in dev | `test_outside_dev_a_header_cannot_change_who_decides` | `assert 200 == 403` |
| Literal credential refused | `test_a_literal_credential_in_a_header_is_refused` | `assert (200 == 400)` |
| Expired approval | `test_an_expired_approval_lets_no_call_through` | `KeyError: 'denyReason'` (the call was allowed) |
| Team scoping | `test_a_team_sees_only_its_modules_and_is_told_who_owns_the_rest` | `assert 200 == 403` |
| Schema before egress | `test_input_failing_the_schema_never_reaches_the_upstream`; uc-011 | `assert 403 == 422`; uc-011 check 4 FAIL |
| Hidden operation | `test_a_hidden_operation_is_refused` | `assert (200 == 403)` |
| Unknown tool | `test_a_tool_the_registry_does_not_know_is_refused` | `assert 200 == 403` |
| Egress allow-list | `test_egress_goes_only_to_the_modules_hosts` | `KeyError: 'error'` (the call went out) |
| Output masking | `test_a_read_runs_against_the_upstream_masked_and_logged_with_its_caller` | the identifier came back unmasked |
| Registry and catalogue agree | `test_the_registry_and_the_agents_catalogue_agree_on_every_access_class` | `place_wire_hold ('money_movement', 'stub') != ('money_movement', 'local')` |
