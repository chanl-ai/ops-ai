# Service test speed and pruning

Status: current. Where each service suite spends its time, what was changed in the test rig to make it faster, and
every test deleted for being redundant, with the test that still covers it.

## Where the time goes (measured 2026-11-16)

Each figure is one `make -s test PKG=services/<svc>` run, on a machine with 14 cores and a load average of 6 to 8 from
other builders' suites.

| Service | Tests | Wall clock | Main cost |
|---|---|---|---|
| tools-service | 975 | 869 s | Spread thinly over 943 tests (the slowest 8.6 s, a timeout mock); not profiled further |
| agents-service | 1,871 | 724 s | CPU in the test process: each test starts its own app, and FastAPI builds a route's dependants and pydantic fields on the first request to it (about 0.2 to 0.5 s per app). Profiled on four API files, 26 of 35 s went to `fastapi.utils.create_model_field`. |

What it is not, for agents-service: emptying the 58 tables before a test takes 25 to 65 ms; starting the app's
lifespan (seeding) takes about 70 ms; `create_app` itself takes 8 ms; the schema is migrated once per run, not per test.
Real sleeps (timer, lease and mail tests) add about 60 to 70 s in total; they are left as they are, since those files
are lease and timer conformance tests that builders are editing.

The cost is per test and CPU-bound, so it divides across processes: the fix is a parallel run with one database per
worker, below.

## Parallel runs

`make -s test PKG=services/<svc> PAR=<n>` runs the suite on n pytest-xdist workers. `scripts/test_db.py --workers n`
migrates the run's test database once and copies it per worker (`<name>_gw0` …), and each worker's conftest points
itself at its copy (`ops_service_kit.testdb.use_worker_database`), which leaves the live-database guard's pair untouched.
A whole test file runs on one worker. A suite runs in parallel only once it is listed in `PAR_SUITES` (make/env.mk),
after three parallel runs in a row with no failure that a serial run does not also have; any other suite refuses `PAR=`.
CI shards are unchanged: a shard runs serially.

| Service | Serial | PAR=5 (three runs) | Failures in every run, serial and parallel alike |
|---|---|---|---|
| agents-service | 724 s | 178, 180, 173 s; 201 s on the final tree, all green | `test_tools_ownership.py::test_tools_chain_adopts_tables_the_agents_chain_created` (also red in the serial baseline); three in `test_workflow_tools.py` and `test_child_runs.py` from source edits in progress on the branch |
| tools-service | 869 s | 205, 203, 201 s | none (skips are the SQL Server tests, which need OPS_MSSQL_SERVER, as serially) |
| platform-service | 287 s | 94, 93, 95 s (PAR=4) | none |
| documents-service | 73 s | 35, 35, 37 s (PAR=4) | none |
| files-service | 44 s | 24, 22, 22 s (PAR=4) | none |
| models-service | 46 s | 22, 22, 21 s (PAR=4) | none |
| kb-service, not enabled | 153 s | 53, 49, 49 s (PAR=4) | the second run failed two `test_settings_audit.py` tests that passed in the other two, and the third skipped five more tests than the first; serial runs also deselect 207 tests that parallel runs do not report, so kb stays serial until that is explained |

## Deleted tests

| Test | Reason | Surviving cover |
|---|---|---|
| agents-service `tests/test_settings_without_shared_token.py::test_a_leftover_shared_token_in_the_environment_is_ignored` | Passes because pydantic-settings ignores unknown variables (`extra="ignore"`) and the field is gone; it tests the library and removed code | none: no code reads `OPS_SERVICE_TOKEN` |

Kept: `test_production_settings_start_without_a_shared_service_token`, which fails if `service_token` comes back as a
settings field, optional or required; it guards the tokens area, which is not pruned.

A strict read of agents-service's `unit/` and `api/` files found no other test that meets the rules: near-duplicates
there hit different routes or stores (different seams), and the excluded kinds (reply pins, isolation, migrations,
sign-in, leases and timers, budgets, loop health) were not read for deletion. Not yet read for pruning: agents
`engine/`, `store/`, `gateway/`, `api/test_memory.py`, and the other services.

## Shared packages, scripts and the smaller services (read 2026-11-16)

### How much the branch added

Test functions (`def test_`) at `origin/develop` and at the branch head. An earlier count of 269 for the first row
left out `packages/`, because the path pattern matched nothing on develop; the figures below are from
`git grep -c` on each tree.

| Directory | develop | branch head | Added |
|---|---|---|---|
| `packages/*` | 613 | 738 | 125 |
| `scripts/tests` | 236 | 304 | 68 |
| `deploy/database/tests` | 33 | 38 | 5 |
| platform-service | 298 | 331 | 33 |
| kb-service | 203 | 237 | 34 |
| documents-service | 103 | 129 | 26 |
| files-service | 86 | 99 | 13 |
| models-service | 97 | 125 | 28 |
| runner-service | 15 | 22 | 7 |
| Total read here | 1,684 | 2,023 | 339 |
| agents-service and tools-service (not read here) | 2,319 | 2,395 | 76 |

### Merged groups

| Directory | Functions before | After | Cases before | After | Wall clock before | After |
|---|---|---|---|---|---|---|
| `scripts/tests` | 304 | 288 | 340 | 341 | 313 s | 344 s |
| `packages/ops_policy` | 34 | 27 | 60 | 62 | 0.11 s | 0.06 s |

Both `scripts/tests` runs were on a machine with a load average of 12 to 14, so the 31 s between them is load. The
merged tests are pure function calls that take milliseconds; merging them changes the count and not the time.

| Group | What changed | Why | Surviving cover and its mutation |
|---|---|---|---|
| `test_scrub_board_paths.py`, 10 to 5 | Five `rewrite` tests became one table; two `leaks` tests became one | Same call, one input and one expected string each | `test_a_path_or_login_is_rewritten_and_nothing_else`: with the workspace prefix swap removed, the `sibling` row fails |
| `test_check_config_literals.py`, 10 to 6 | Five `findings` tests became one table of five sources | Same detector, one source and one finding list each | `test_each_literal_is_found_in_every_form_and_look_alikes_are_not`: with the positional `wait_for` limit ignored, the `forms` row fails |
| `test_check_typed_boundaries.py`, 10 to 8 | Three `findings` tests became one table of four rows | As above | `test_each_kind_is_found_in_every_form_and_look_alikes_are_not`: with the store-dict finding removed, the `store` row fails |
| `test_check_portable_store.py`, 10 to 8 | Three `slice_findings` tests became one table | As above | `test_a_page_cut_in_python_is_found_in_every_form_and_other_slices_are_not`: with named `islice` ignored, the third row fails |
| `test_dependants.py`, 8 to 5 | Four `plan` tests became one table of five rows | Same call to `verify-changed.sh`, one changed path and one expected line each | `test_a_change_plans_and_starts_exactly_the_suites_that_depend_on_it`: with the unknown-package branch removed, the `unknown-package` row fails |
| `ops_policy/tests/test_tokens.py`, 8 to 5 | Five step-up refusals became one table | Same `verify_step_up` call, one reason each; every reason kept | `test_a_step_up_that_proves_nothing_is_refused`: with `too_old` raised as `expired`, the `shorter-window` row fails |
| `ops_policy/tests/test_ed25519.py`, 11 to 7 | Five refusals (six cases) became one table | Same `verify` call, one reason each; every reason kept | `test_a_token_that_proves_nothing_is_refused`: with the unbound-audience refusal removed, the `unbound` row fails |

In `test_ed25519.py` the `widened` row (a call naming another audience than the verifier's) still passes when the
bound-verifier refusal at `tokens.py:171` is removed, because the claim check at `tokens.py:204` refuses the same
token. The test it came from behaved the same way.

### What was read and left as it is

Total: 23 functions merged away (16 in `scripts/tests`, 7 in `ops_policy`), none deleted, no time saved. The commit
that merged the script tests says 17 and 287 in its message; 16 and 288 are right.

The tests this branch added were read by name in every directory above (the added `def test_` lines of
`git diff origin/develop..HEAD`). Bodies were read only in the five script files and two `ops_policy` files merged
above, `test_impacted_tests.py`, and the four kb page tests named below. A name was enough to place a test in a kind
that is not pruned; it does not show whether two tests of one kind repeat each other.

| Area | Added | Why it stays |
|---|---|---|
| `ops_store` (`test_install_scope`, `test_copies`, `test_listing`, `test_owner_teams`, `test_isolation_sites`, `test_background`, `test_outbox`, `test_loop_health`) | 83 | Install-scope guard, tenant and team isolation, lease and outbox conformance, loop health and statement counts: each function is one failure mode and the kinds are not pruned |
| `ops_identity/test_request_transaction.py` | 9 | By name: one failure mode each of the request transaction (rollback, savepoint, stream, pool) |
| `scripts/tests` check self-tests not listed above | about 50 | By name, and by body in the three check files merged above: each function is one rule's bad case and good case in one body already; the three per-check baseline-history tests each prove that check hands its own baseline file to the shared gate |
| platform-service | 33 | List isolation per list, reply and body pins (one table each), lockout, both-database runs, statement budgets, loop health |
| kb-service | 34 | The same kinds; the four `*_page_keeps_another_teams_rows_out_by_its_own_predicate` tests are one per list with different rows to seed, which is the one-per-table rule |
| documents, files, models, runner | 74 | By name: reply and body pins, list order and paging, no-transaction-open gates, spend settled after a disconnect, budgets, loop health |
| `ops_service_kit` | 28 | By name: endpoint settings, the list contract, the OpenAPI gate, the standards and typed-boundary walks, the worker database guard |
| `deploy/database/tests` | 5 | By name: index cover and isolation markings; two of its files hold another builder's uncommitted edits |

### Left to do

The 23 above are what one pass reached, and more is likely in the older tests. About 1,680 functions in these
directories are older than the branch and almost none were read; the four older files that were read gave 15 of
their 37 functions.

| Left | Why it is next |
|---|---|
| Older per-route tests in platform-service and kb-service that the branch's table-driven pins now cover (`test_reply_pins.py`, `test_body_name_pins.py`, `test_list_routes.py`, `test_statement_budget.py`) | The builder rules say to delete an older test when a new table covers it; nobody has compared them. These are real deletions and each one saves an app start |
| The same comparison in documents, files, models and runner | As above |
| Older files with many short tests: `scripts/tests/test_impacted_tests.py`, `test_install_cli.py`, `test_setup.py`; `ops_ingest/tests/test_parsers.py`, `test_split.py`, `test_reading.py`; `ops_policy/tests/test_jcs.py`; `ops_service_kit/tests/test_template_merge.py`, `test_flags.py`; `ops_access/tests/test_effective_answer.py`, `test_can.py`; `ops_extract/tests/test_checks.py`; `ops_plugin_sdk/tests/test_manifest_fields.py`, `test_validate.py`; `ops_store/tests/test_dialect.py`; runner `test_sandbox.py`; models `test_models.py` | Candidates for tables by shape (under 15 lines a test); not read |
| `deploy/database/tests/test_indexes.py`, `test_isolation_markings.py`, `packages/ops_store/tests/test_isolation_sites.py`, `scripts/tests/test_team_boundary.py` | Held another builder's uncommitted edits during this pass |

### Where the `scripts/tests` time goes

Four tests take 151 of the 344 s, and each starts real tools in a subprocess (ruff, pyright, the console typecheck,
a stack): `test_verify_staged.py::test_a_clean_typed_file_passes_with_its_imports_read_once` (60 s),
`test_page_stack.py::test_a_page_naming_platform_services_gets_them_with_its_people_signed_in` (55 s),
`test_checks_list.py::test_staged_runs_a_check_only_when_a_staged_path_can_change_it` (21 s) and
`test_verify_staged.py::test_a_console_change_still_runs_the_console_typecheck` (16 s). Shortening this suite means
making those four cheaper; the function count has little to do with it. The list comes from
`uv run pytest scripts/tests -q -p no:cacheprovider --durations=15`.
