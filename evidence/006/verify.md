<!-- codeloop verify: start -->
# Verify c-006

result: pass
sha: 01d631bf4361c14e8101004fc210b3b122cabb16
env: local

| Use case | Accepts | Layers |
|---|---|---|
| us1-sign-in-refresh-and-sign-out | US1 | cli pass |
| us2-members-roles-and-removal | US2 | cli pass |
| us3-every-write-is-audited | US3 | cli pass |
| us4-anonymous-and-foreign-tokens-refused | US4 | cli pass |
| us5-another-service-verifies-locally | US5 | cli pass |
<!-- codeloop verify: end -->

# Verify c-006

## Runs on a clean export

Status: recorded by the builder, 2026-10-11, on a detached worktree at d9b2684 with its own databases and ports
(`ops_test_c006v`, `ops_usecase_c006v`, ports 8950 to 8954 and 3258). Each line is the command from the verification
block in the card's spec and the output it printed.

| Check | Command | Result |
|---|---|---|
| platform-service | `make -C services/platform-service verify` | 67 passed; openapi 19 operations, 0 untyped; exit 0 |
| uc-021 | `make usecase-test UC=uc-021 LAYER=api` | 8 checks passed; exit 0 |
| uc-023 | `make usecase-test UC=uc-023 LAYER=api` | 6 checks passed; exit 0 |
| uc-025 | `make usecase-test UC=uc-025 LAYER=api` | 5 checks passed; exit 0 |
| uc-026 | `make usecase-test UC=uc-026 LAYER=api` | 4 checks passed; exit 0 |
| US5 | `cd packages/ops_identity && uv run pytest` then platform-service's suite with the seam test | 20 passed; 67 passed; exit 0 |
| Whole repo, first run | `make verify` | exit 2: agents-service `test_an_agent_retry_after_a_crash_repeats_no_tool_call` saw `place_wire_hold` refused, 1 failed and 200 passed |
| Whole repo, rerun | `make verify` on a fresh database, same commit | exit 0 |
| All use cases | `make usecase-test` | every registered layer passed except uc-027 api, which failed 2 of 6 checks; exit 2 |
| uc-027, rerun | `make usecase-test UC=uc-027 LAYER=api`, same commit | 6 checks passed; exit 0 |

## The two first-run failures

Neither is in this card's code, and neither reproduced. The agents-service test passed alone at d9b2684 three
times, at 6132606 and at 7597d8c on fresh databases, and after tools-service's suite on the same database at both
earlier commits. The whole agents suite passed on a fresh database at all three commits. uc-027 depends on a token
expiring one second after a decision and passed on rerun; the first run shared the machine with the full suite.
Both are recorded as intermittent, for agents-service's owners, rather than as passes.

## Non-vacuous checks seen failing

| Use case | Guard removed | Failed check |
|---|---|---|
| uc-021 | revocation on refresh-token reuse | the reuse ended the session for its current token too (200) |
| uc-023 | the last-admin rule | demoting the only admin is skipped with a reason |
| uc-025 | the admin check on the audit route | a viewer reading the audit is 403 (200) |
| uc-026 | an added route with no authentication | all 13 non-public operations are 401 without credentials |
