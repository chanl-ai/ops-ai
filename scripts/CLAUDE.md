# Scripts: working rules

Status: current.

Repository tooling: the process manager behind `make up`, the commit and docs gates, generators that keep docs in step
with code, the API-as-a-person helpers, demo installers and dependency tools. Nothing here ships in an image. Most
scripts are reached through a make target; run them that way so ports and env match the stack
([docs/architecture/make.md](../docs/architecture/make.md)). Rules shared with every folder:
[Working in one folder](../CLAUDE.md#working-in-one-folder).

## What is here

| Group | Scripts | Reached by |
|---|---|---|
| The stack | `stack.sh` (start, stop, probe, tail, stale detection), `schema_sync.py` (may `make up` migrate in place), `test_db.py` (the throwaway test database, cloned from a migrated template), `new_migration.py` (`make migration`: a UTC-timestamp revision id), `builder-watch.sh` (`make builder-watch`: stalled worktrees), `dev_admin.py`, `dev_egress.py`, `secrets_cmd_env.py` (OPS_SECRETS_CMD output for make/env.mk), `scratch_db_sweep.py` (`--prune` is `make test-db-prune`: idle `ops_test_*`/`ops_usecase_*` databases older than HOURS), `api_docs.py` (all services' API reference on :8799) | `make up`, `make health`, `make logs`, `make test`, `make db-sweep` |
| Calling the API as a person | `api_as.py` (every other area runs the `opsai` command in `sdk/python`) | `make api`, `make sdk-call` ([make/CLAUDE.md](../make/CLAUDE.md)) |
| Commit and push gates | `verify-staged.sh` (pre-commit, on the staged content), `commit-message-check.mjs`, `changelog-check.mjs` (commit-msg), `verify-changed.sh` (what changed since a base), `verify-head.sh` (`make verify` on an export of HEAD), `commit-paths.sh`, `commit-patch.sh`, `install-hooks.sh`, `git-rules.py`, `agent-guard.py` (refuses whole suites, bare pytest, pnpm verify and sleeps over 60 s when CL_AGENT or CL_AGENT_RUN is set), `impacted_tests.py` (the tests a change can affect) | `.githooks/`, `make commit`, `make commit-hunks`, `make test`, `make test-impacted`, `make git-rules`, `make agent-guard` ([Commits](../CLAUDE.md#commits)) |
| Docs and generated-file checks | `check-docs.mjs`, `check-doc-routes.mjs` (every console route in a table of `docs/architecture/console-areas.md` is a page the console serves), `check-guides.mjs` (every agent guide's links, paths and make targets), `check-known-traps.mjs` (each guide's "Known traps" section holds at most 12 lines, each `trigger => fix`; runs in `make checks`), `check-standards-refs.mjs` (every agent and folder guide links its [engineering standards](../docs/architecture/engineering-standards.md) page, and every cited rule id such as `DA5` exists), `check-public-paths.mjs`, `scrub_board_paths.py`, `agent_skills.py`, `wf_builder_examples.py`, `check_examples.py` | `make docs-verify`, `make docs-guides-check`, `pnpm verify` |
| Code standards checks | `check_access_exceptions.py` (access decisions outside `can()`), `check_portable_store.py` (storage code that runs on PostgreSQL and not on SQL Server), `check_config_literals.py` (a loopback fallback anywhere; a literal timeout or an `httpx.AsyncClient(` beyond the member's `config-literals-baseline.txt`), `check_console_baselines.py` (the console's `*-baseline.json` rise history), `check_tests_typecheck.py` (strict pyright for a member, run by each service's typecheck target and `typecheck-packages`: zero errors outside tests, and a test file no more than its row in the member's `tests-typecheck-baseline.txt`, which only falls; `--update` lowers, `--seed` writes a first file), `ensure-sdk-ts-built.sh` (rebuilds `sdk/typescript` before the console typecheck when its sources are newer than its dist), `check_typed_boundaries.py` (a `dict[str, Any]`, a dict-returning store function, a gather, a bare task, an `extra="allow"`, a route body not an `In` or reply not an `Out`, beyond the member's `typed-boundaries-baseline.txt`; any `print(` or `logging.getLogger(`), `check_gateway_routes.py` (a `/api/<service>/` path the console's clients call that no gateway config under `deploy/` routes), `check_downgrades.py --all` (an empty `downgrade()`, beyond `downgrades-waiting.txt`, which only shrinks), `check_migration_heads.py` (a `services/*/migrations/versions` chain with more than one head, naming both), `check_service_standards.py` (the kit's rules 4 to 6 for every service but agents-service, whose `check_standards.py` runs them; its `WAITING` count only falls), `leak_scan.py` | `make python-verify`, CI |
| Docs written from code | `roles_matrix.py` (roles grid in `docs/architecture/roles-and-permissions.md`), `store_inventory.py` (`docs/architecture/data.md`), `sbom.py` (`docs/architecture/dependencies.md`); in `sdk/`, `changelog_from_api_changes.py` (the breaking block of `docs/sdk/changelog-next-major.md` from `docs/architecture/migration/api-changes.md`; `--check` prints the difference) and `api_changes_gap.py` (a route whose committed `openapi.json` changed and that `api-changes.md` does not name) | `make python-verify` runs each with `--check`, and `make checks` the two `sdk/` ones; run without it to rewrite |
| The list of checks | `make/checks.mk` runs `check_access_exceptions.py`, `check_portable_store.py`, `check_config_literals.py`, `check_typed_boundaries.py`, the downgrade, token-lifetime, cross-service and code-rule checks and the rest of one list; `baseline_history.py` reads each baseline's history, and a rise waits for an approving review on the pull request from a maintainer in `.github/standards-maintainers.txt` (by hash), which `check_review_approval.py` reads from GitHub in CI (only an approval on the head commit, or after which nothing was raised; the maintainer-review job runs the base revision's copies of these files, and an edit to them is a rise); a rise fails unless approved: `make checks` and pre-commit only defer it (printed as not checked), `make checks-history` (also in `make verify`) reads the review with `check_review_approval.py --local` and is red without one; `tests/test_checks_list.py` proves every place that checks runs the list | `make checks`, `make verify`, pre-commit, CI |
| Use cases and CI | `usecase.mjs` (entry to `packages/usecase-runner`), `at-most.py` (slots), `ci-plan.sh`, `ci_local.py` (`make ci-local`: the planned jobs in parallel), `ci_usecases.py` (`make usecase-pick`: the use cases a diff affects; `run` honours the quarantine; `report` is the nightly's record), `quarantine.py` (`make quarantine`; the list is `config/quarantine.json`), `test_shard.py`, `dependants.py`, `keep_going.sh` | `make usecase-test`, `.github/workflows/ci.yml`, `make python-verify` |
| Demo and sample data | `sample_team.py`, `sample_walk.py`, `sample-team/`, `demo_model.py`, `demo_salesforce.py`, `demo-salesforce/walk.mjs`, `check_demo_team.py`, `live-app-check.mjs` | `make sample-team`, `make demo-walk`, `make demo-model`, `make demo-salesforce*` |
| Workflow builder skill | `wf_builder.py`, `wf_builder_examples.py` | the `/wf-builder` skill (`docs/guide/skills/`) |
| Setup and dependencies | `setup/` (`make setup`), `deps_doctor.py`, `deps_relock.sh`, `deps_audit.py`, `deps_smoke.sh`, `install_via_mirror.sh` | `make setup`, `make deps-*`, `make qa-mirror`, `make install-mirror` |
| Docs builds | `docs/build_guide.mjs`, `docs/mermaid_svg.mjs`, `docs/screens.mjs` | run by hand with `node` |
| Agent scripts | `agents/review_context.py` (the reviewer's bundle), `agents/test_audit.py` (mutation on changed lines, tests that cannot fail, failure modes with no test), `agents/ui_walk.mjs` (routes as each role at each width), `agents/seed_canaries.py` (planted bugs and the finder score), `agents/project_profile.py` and `.mjs` (the profile reader) | `make agent-*` (`make/agents.mk`), `CONTRIBUTING.md` "Agents and their scripts" |
| Proofs and probes | `disk_proof.sh`, `skills_proof.sh` (`make skills-proof`), `team_isolation_probe.py`, `perf/time_routes.py`, `proof-*.sh`, `release-tag.sh` (`make release-tag`), `release-main.sh` (`make release-main`), `release.py` (`make release-intake`, `release-cut`, `release-pr`, `release-version`, `hotfix-cut`), `qa.sh` (asks a QA runner for a verdict on a commit; needs one set up through `QA_DIR`) | by hand or their make target |

## Tests

`scripts/tests/` holds one test file per script that has rules worth breaking (`test_<script>.py`), run by
`make python-verify` and CI as `uv run pytest -q scripts/tests`.

| Task | Command (repo root) |
|---|---|
| One script's tests | `uv run pytest -q scripts/tests/test_commit_paths.py` |
| All of them | `uv run pytest -q scripts/tests` |
| The pre-commit hook end to end, in a throwaway clone | `bash scripts/tests/test-verify-staged.sh` |
| The agent scripts' own cases | `make agent-scripts-test` (each script's `--self-test`; the audit's plants faults and watches them survive once their test is removed) |
| The JS gates' own cases | `node scripts/commit-message-check.mjs --self-test`, `node scripts/changelog-check.mjs --self-test`, `node scripts/check-public-paths.mjs --self-test`, `node scripts/check-doc-routes.mjs --self-test`, `node scripts/check-guides.mjs --self-test`, `node scripts/check-standards-refs.mjs --self-test`, `node scripts/check-known-traps.mjs --self-test`, `python3 scripts/git-rules.py --self-test`, `python3 scripts/agent-guard.py --self-test` |
| Lint and format | `uv run ruff check scripts` and `uv run ruff format --check scripts` |

## Rules

| Rule | Detail |
|---|---|
| Stack scripts never touch a test's database, and tests never drive the stack | `test_db.py` refuses the stack's database (`ops_runtime`); `make/env.mk` refuses stack goals under pytest |
| Read settings through `ops_service_kit` | Python scripts that need a port, URL or password read `ops_service_kit.settings.Settings` or the `OPS_*` names `make/env.mk` sets, as `api_as.py` does |
| A generator has a `--check` | A script that writes a doc or file from code fails under `--check` when the committed copy is stale, and a gate runs that check |
| A gate is proven red | Each gate keeps red and green cases (`--self-test` or a file in `scripts/tests/`) that fail when the rule is removed |

## Known traps

- Tests passed on a laptop and failed in CI => CI runs the tests with `GITHUB_ACTIONS` set, so a script that reads it (`release-tag.sh`: `GITHUB_ACTIONS`, `WALK_PASSED`; `ci-plan.sh`: `GITHUB_REF`, `GITHUB_EVENT_NAME`, `CI_FULL`) is tested with an explicit env that drops or sets them (`tag()` in `test_release_tag.py`, `plan()` in `test_ci_plan.py`); run a suite with `GITHUB_ACTIONS=true` exported to see what CI sees
- A queue merge commit has no type in its subject => `release-tag.sh` reads `feat`/`fix` from the pull request title, which is the first body line of a `Merge pull request #N` commit; a squash commit has it as the subject (`test_release_tag.py`)
- A pick wider than one run fits is cancelled and records nothing => `ci_usecases.py pick` returns nothing above `MAX_PICK` and prints why (the nightly covers it); `run` rewrites its `--out` file after each use case, so a cut-off run still leaves results
- A registry row marked `failing` gates against an empty quarantine => A status cell has no owner or expiry, so `ci_usecases.py` ignores it: a known-failing use case is an entry in `config/quarantine.json` (owner, 30-day expiry). An id is `uc-<digits>` or a name such as `uc-workflows-1`, and `uc-012` equals `uc-12`. CI passes bare ids, so a `:ui` entry quarantines every layer of that use case
- `run` crashed on its own arguments while `--self-test` stayed green => A self-test that never calls `main` cannot catch a wrong call; `ci_usecases.py --self-test` drives `run --out` through `main` with a stubbed runner and reads the file after the first result
- One commit got two tags (`v1.3.0`, then `v1.4.0`) => `release-tag.sh` skips a commit that already holds a `vX.Y.Z` tag before it computes a version, so a rerun or a run by branch name adds none
- An empty pick still ran `run` and failed (exit 2) => `pick` printed a blank line, which the workflow read as the output " " (not empty), and `run` required ids; `pick` now prints nothing when empty, ci.yml trims the list, and `run` with no ids writes an empty result file and exits 0
- A merged `release/*` or `hotfix/*` branch that cannot be deleted froze staging for ever => `staging_hold.py` ignores a branch whose head is an ancestor of the deployed commit (notice printed); an unreadable head still freezes
- A stale `STAGING_HOLD` made a skipped deploy a green run => A live hold or a release or hotfix branch freeze now fails the staging job, the value must be `X.Y.Z: reason`, and a hold whose tag `vX.Y.Z` exists is ignored (`staging_hold.py`, `test_staging_hold.py`)
- A queue run failed with `JSONDecodeError` reading the results file => `Path.write_text` truncates before it writes, so a reader (the self-test, a later workflow step) saw an empty file mid-run; every shared JSON file is written with `atomic_json.write_json` (temp file, then `os.replace`): `ci_usecases.py`, `ci_local.py --out`, `quarantine.py` (`test_atomic_results.py`)
- A quarantine entry is capped at 30 days => `quarantine.py check` rejects a later expiry than 30 days after `added`; `make checks` runs it on every pull request
- A workflow_run or schedule workflow starts only from the default branch => `release-tag.yml` and `nightly-usecases.yml` do nothing until they are on `main`; start them once by hand (`docs/deploy/release.md`, First run)

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [delivery, deploy and upgrade](../docs/architecture/standards/delivery.md) (`DL1` to `DL9`), [tests](../docs/architecture/standards/testing.md) (`TS1` to `TS8`). The index of every rule is
[engineering standards](../docs/architecture/engineering-standards.md); a review cites the rule id.
