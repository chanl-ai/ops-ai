# Standards: delivery, deploy and upgrade

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `DL1` to `DL9` are frozen.
The pipeline is in [delivery](../delivery.md), [operations](../operations.md) and `deploy/CLAUDE.md`.

Every change is reviewed and attributable, one gate decides a merge and the same gate runs locally, every merge reaches
staging under the real migrations, production gets only a tagged commit staging ran, and every check has been seen
failing.

## DL1 A branch, a pull request, never the trunk

Rule: work lands on a branch named `<type>/<scope>-<what-changed>` through a pull request; nobody pushes to the trunk or
`main`, force-pushes, stashes on a shared tree or skips a hook.
Why: every change is reviewed and attributable (SOC 2 CC8.1).

Pattern (`scripts/git-rules.py`): refuses stash, hard reset, clean, skipped hooks, force push and a push to the trunk,
as a Claude Code hook; `make git-rules` self-tests it.

The installed launcher refuses a commit or push when the checkout has no `.githooks/<hook>`. A local hook can still be edited or bypassed, so CI is the backstop for every check a hook runs.

Check: `scripts/git-rules.py`; `.githooks/` installed by `scripts/install-hooks.sh`; branch protection on the trunk.

## DL2 One gate, the same locally and in CI

Rule: a merge is blocked unless `ci-ok` passed for that commit, and `make verify` runs the same checks locally: lint
and format, strict types, import contracts, every standards check on these pages, the affected test suites, the SDK
drift check, `pnpm verify`, the docs checks and the leak scan.
Why: a check that runs only nightly finds the breach a day after it merged.

Today (`make/checks.mk`): `CHECKS` is the one list of standards checks (the access, portable-store, config-literal
and typed-boundary ratchets and their history, the isolation markings and indexes, the isolation, relay and loop-health
sites, the files written from code, import contracts, the SDK drift check, the changelog entries, the console's
standards). The pull-request `checks` job, `make verify` (through `python-verify`), `scripts/verify-changed.sh` and
pre-commit (`make checks STAGED=1`, which runs a check when a staged path can change it) all run `make checks`. The
leak scan and CodeQL run and are not required on the development trunk.

Pattern (`.github/workflows/ci.yml`): `ci-ok` is the one required job; `scripts/ci-plan.sh` picks what runs from the changed
paths: a documents-only change (markdown or `docs/`) runs the docs job and the leak scan; a service's jobs run when
it, its packages or a shared package changes; the console job on `apps/` or `sdk/`; `store-mssql` on any change
under `services/`, `packages/` or `deploy/database/`. A skipped job counts as passed in
`ci-ok`. `[ci full]` in the pull request title, or the `ci:full` label, runs every job.

Before a pull request is pushed, the tests of the files it touches pass (`make test`, which selects from `origin/develop`); the hosted run gates, and the merge queue runs the heavy jobs. `make ci-local FULL=1` reproduces a red heavy job locally.

Check: `.github/workflows/ci.yml` job `ci-ok`; `make checks`; `scripts/tests/test_checks_list.py` (every check named
in it runs from `make checks`, and every place that checks calls it). Needed: make `scan` and CodeQL required.

## DL3 A reviewer who did not write it

Rule: a merge needs approval from a reviewer who did not write the change; an agent reviews under its own name, never
the builder's.
Why: separation of duties for change management (SOC 2 CC8.1).

Today: branch protection requires zero reviews on both trunks.

Check: no check yet. Needed: branch protection requiring one approving review.

## DL4 Every merge reaches staging under the real migrations

Rule: each merge to the trunk deploys to staging, which runs every migration chain, applies grants, checks every process
and walks the console headless; a failed smoke stops promotion.
Why: staging tests the real combination before people do.

Today (`.github/workflows/deploy-staging.yml`): ci.yml's `staging` job calls it after `ci-ok` on every push to
develop and on every push to a `release/*` or `hotfix/*` branch (`!cancelled()` keeps it from being skipped when the plan skipped a job), and it runs by hand for any ref. A develop push is skipped while any release or hotfix branch exists on origin, so a release under test is not overwritten.
`deploy/fly/stg_deploy.sh` does everything the rule asks; a failed check after the machine changed rolls back to the
release before. Not yet run on GitHub.

Pattern (`deploy/fly/stg_deploy.sh:1`): build from `git archive`, migrate as the release command, apply grants, check
processes, OCR, plugins, a signed-in request, then the click walk.

Check: `.github/workflows/deploy-staging.yml` running `make stg-deploy`; `make stg-health`; the use cases' api scripts
run against the deployed host with `OPS_USECASE_BASE_URL=https://<host>` (`docs/usecases/README.md`). Needed: the first
run after merge, which proves the `staging` environment's secrets and the rollback.

## DL5 Production gets a tagged commit staging ran

Rule: production deploys only a tag `vX.Y.Z` on a commit staging ran; migrations apply before new processes
start; rollback redeploys the previous image; migrations only add (`DA10`).
Why: promotion is repeatable and reversible.

Today: `.github/workflows/release-finish.yml` tags the merge of a release or hotfix pull request into `main` (`docs/deploy/release.md`); no workflow deploys the tag. A workflow returns once
the owner has made the `production` environment (`docs/deploy/fly-staging.md`, "Production on GitHub"). `release-images.yml`
has never built from a merged commit.

Pattern (`make stg-rollback`, `deploy/fly/stg_deploy.sh`): the staging path is the production path with another target.

Check: `.github/workflows/release-finish.yml`; `make stg-rollback`. Needed: the production deploy workflow, after the
owner's set-up in `docs/deploy/fly-staging.md` ("Production on GitHub").

## DL6 An upgrade from the previous release is proven

Rule: every release proves the upgrade from the previous release's schema and a from-scratch install, with both
databases' DDL generated and checked.
Why: a migration that only works on a database with history fails the first install, and one that only works from empty
fails every customer.

Today: the upgrade from the previous schema runs inside `make stg-deploy` and, on a pull request into `main`, in the
`release-proof` job (`make db-scripts-proof FROM=<last tag>`, then `make install-proof` on the released images).

Pattern (`make db-scripts-proof`): a release's baseline and the upgrade from `FROM=<tag>`, in `dist/db/<tag>`.

Check: `deploy/database/tests/test_runtime_logins.py` (down and up per chain from empty), `test_mssql_ddl.py`,
`test_model_parity.py`; `.github/workflows/ci.yml` job `release-proof`, required through `ci-ok`.

## DL7 Commits and What's new explain themselves

Rule: a commit is `type(scope): subject` under 72 characters with a body of at most three lines saying why the old
behaviour was wrong and what ran; a user-visible `feat` or `fix` carries a `Changelog:` trailer and its entry.
Why: the history explains itself to a reader with only this repository.

Check: `scripts/commit-message-check.mjs` and `scripts/changelog-check.mjs` in the `commit-msg` hook;
`node scripts/changelog-check.mjs --entries` in CI.

## DL8 Docs change with the code

Rule: a change that alters a rule on these pages, a contract, a data model or a folder's layout updates the page or
guide that owns it in the same change; every agent and every folder guide links its standards.
Why: a doc that lags the code stops people checking it.

Check: `node scripts/check-docs.mjs`; `node scripts/check-guides.mjs`; `node scripts/check-standards-refs.mjs`
(`make docs-guides-check`).

## DL9 Every check is seen failing once

Rule: a check on these pages is trusted only after it has failed on a planted breach; each gate script keeps a
`--self-test` or a red case in `scripts/tests/`.
Why: a check never seen failing may not detect the breach it names.

Pattern (`scripts/check-guides.mjs:77`): `selfTest()` plants five misses and asserts five are found.

Check: `make agent-scripts-test`; each script's `--self-test` (`scripts/CLAUDE.md`, "Tests"); `scripts/agents/seed_canaries.py`
for the review agents.
