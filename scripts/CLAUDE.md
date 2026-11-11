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
| The stack | `stack.sh` (start, stop, probe, tail, stale detection), `schema_sync.py` (may `make up` migrate in place), `test_db.py` (the throwaway test database), `dev_admin.py`, `dev_egress.py`, `scratch_db_sweep.py`, `api_docs.py` (all services' API reference on :8799) | `make up`, `make health`, `make logs`, `make test`, `make db-sweep` |
| Calling the API as a person | `api_as.py` (every other area runs the `opsai` command in `sdk/python`) | `make api`, `make sdk-call` ([make/CLAUDE.md](../make/CLAUDE.md)) |
| Commit and push gates | `verify-staged.sh` (pre-commit, on the staged content), `commit-message-check.mjs`, `changelog-check.mjs` (commit-msg), `verify-changed.sh` (what changed since a base), `verify-head.sh` (`make verify` on an export of HEAD), `commit-paths.sh`, `commit-patch.sh`, `install-hooks.sh`, `git-rules.py` | `.githooks/`, `make commit`, `make commit-hunks`, `make test`, `make git-rules` ([Commits](../CLAUDE.md#commits)) |
| Docs and generated-file checks | `check-docs.mjs`, `check-public-paths.mjs`, `scrub_board_paths.py`, `agent_skills.py`, `wf_builder_examples.py`, `check_examples.py` | `make docs-verify`, `pnpm verify` |
| Code standards checks | `check_access_exceptions.py` (access decisions outside `can()`), `check_portable_store.py` (storage code that runs on PostgreSQL and not on SQL Server), `check_downgrades.py`, `leak_scan.py` | `make python-verify`, CI |
| Docs written from code | `roles_matrix.py` (roles grid in `docs/architecture/roles-and-permissions.md`), `store_inventory.py` (`docs/architecture/data.md`), `sbom.py` (`docs/architecture/dependencies.md`) | `make python-verify` runs each with `--check`; run without it to rewrite |
| Use cases and CI | `usecase.mjs` (entry to `packages/usecase-runner`), `at-most.py` (slots), `ci-plan.sh`, `test_shard.py`, `dependants.py`, `keep_going.sh` | `make usecase-test`, `.github/workflows/ci.yml`, `make python-verify` |
| Demo and sample data | `sample_team.py`, `sample_walk.py`, `sample-team/`, `demo_model.py`, `demo_salesforce.py`, `demo-salesforce/walk.mjs`, `check_demo_team.py`, `live-app-check.mjs` | `make sample-team`, `make demo-walk`, `make demo-model`, `make demo-salesforce*` |
| Workflow builder skill | `wf_builder.py`, `wf_builder_examples.py` | the `/wf-builder` skill (`docs/guide/skills/`) |
| Setup and dependencies | `setup/` (`make setup`), `deps_doctor.py`, `deps_relock.sh`, `deps_audit.py`, `deps_smoke.sh`, `install_via_mirror.sh` | `make setup`, `make deps-*`, `make qa-mirror`, `make install-mirror` |
| Docs builds | `docs/build_guide.mjs`, `docs/mermaid_svg.mjs`, `docs/screens.mjs` | run by hand with `node` |
| Agent scripts | `agents/review_context.py` (the reviewer's bundle), `agents/test_audit.py` (mutation on changed lines, tests that cannot fail, failure modes with no test), `agents/ui_walk.mjs` (routes as each role at each width), `agents/seed_canaries.py` (planted bugs and the finder score), `agents/project_profile.py` and `.mjs` (the profile reader) | `make agent-*` (`make/agents.mk`), `CONTRIBUTING.md` "Agents and their scripts" |
| Proofs and probes | `disk_proof.sh`, `skills_proof.sh` (`make skills-proof`), `team_isolation_probe.py`, `perf/time_routes.py`, `proof-*.sh`, `release-tag.sh` (`make release-tag`), `qa.sh` (asks a QA runner for a verdict on a commit; needs one set up through `QA_DIR`) | by hand or their make target |

## Tests

`scripts/tests/` holds one test file per script that has rules worth breaking (`test_<script>.py`), run by
`make python-verify` and CI as `uv run pytest -q scripts/tests`.

| Task | Command (repo root) |
|---|---|
| One script's tests | `uv run pytest -q scripts/tests/test_commit_paths.py` |
| All of them | `uv run pytest -q scripts/tests` |
| The pre-commit hook end to end, in a throwaway clone | `bash scripts/tests/test-verify-staged.sh` |
| The agent scripts' own cases | `make agent-scripts-test` (each script's `--self-test`; the audit's plants faults and watches them survive once their test is removed) |
| The JS gates' own cases | `node scripts/commit-message-check.mjs --self-test`, `node scripts/changelog-check.mjs --self-test`, `node scripts/check-public-paths.mjs --self-test`, `python3 scripts/git-rules.py --self-test` |
| Lint and format | `uv run ruff check scripts` and `uv run ruff format --check scripts` |

## Rules

| Rule | Detail |
|---|---|
| Stack scripts never touch a test's database, and tests never drive the stack | `test_db.py` refuses the stack's database (`ops_runtime`); `make/env.mk` refuses stack goals under pytest |
| Read settings through `ops_service_kit` | Python scripts that need a port, URL or password read `ops_service_kit.settings.Settings` or the `OPS_*` names `make/env.mk` sets, as `api_as.py` does |
| A generator has a `--check` | A script that writes a doc or file from code fails under `--check` when the committed copy is stale, and a gate runs that check |
| A gate is proven red | Each gate keeps red and green cases (`--self-test` or a file in `scripts/tests/`) that fail when the rule is removed |
