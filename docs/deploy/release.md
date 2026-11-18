# Releasing with gitflow

Status: current. `develop` takes every merged change. A release is cut from it as `release/X.Y.Z`, tested on staging,
merged into `main` with a merge commit, tagged `vX.Y.Z`, and merged back into `develop`. A fix to what is already on
`main` is a `hotfix/X.Y.Z` cut from `main` that follows the same path. `git log --first-parent main` then lists only
release and hotfix merge commits. The commands live in `scripts/release.py`; each make target only calls it, and every
one prints what it would do unless `DRY=0`.

## The flow

| Step | Who | Command or action |
|---|---|---|
| 1. Cut | Maintainer | `make release-cut V=X.Y.Z` (preview), then `DRY=0`: pushes `release/X.Y.Z` from `origin/develop`. The push runs `ci.yml`, whose `staging` job deploys the branch with the click walk. A hotfix is `make hotfix-cut V=X.Y.Z`, from `origin/main` |
| 2. Test staging | Maintainer, owner | The click walk of that deploy, use cases against staging (`OPS_USECASE_BASE_URL=https://<staging host> make usecase-test UC=<id> LAYER=api`; only use cases marked safe run, see `docs/usecases/README.md`), and the owner's click-through. Only fixes go on the release branch; each push to it deploys again |
| 3. Open the PR | Maintainer | `make release-pr V=X.Y.Z` (preview), then `DRY=0`: opens `release/X.Y.Z` into `main` titled `release: X.Y.Z (develop → main)` (`release: X.Y.Z (hotfix → main)` for a hotfix) |
| 4. Merge | Owner | A merge commit. No squash and no rebase, so main's first-parent history holds one commit per release |
| 5. Tag | Automatic | `release-tag.yml` tags the merge commit `vX.Y.Z`, the version in the merged branch's name, then starts the SDK publish and the image build for that tag |
| 6. Back-merge | Maintainer | `make release-back-merge V=X.Y.Z` (preview), then `DRY=0`: opens `main` into `develop`, which the owner merges. It must be a real merge commit: the release's merge commit is then in develop's history, and the commit counts below (`rev-list --count origin/develop..origin/main`, the list of merged pull requests in the next release) compare against that history. A squash or rebase leaves main's commits looking unmerged |
| 7. Clean up | Maintainer | Delete `release/X.Y.Z`. While any `release/*` or `hotfix/*` branch exists, a push to `develop` is not deployed to staging |

While a release or hotfix branch exists, staging belongs to it: a develop push skips its deploy with a notice. A push to
the release branch deploys, and so does a deploy started by hand (`make stg-deploy-ci REF=<ref>`). The repository
variable `STAGING_HOLD` freezes staging the same way for any other reason.

A rollback (`make stg-rollback`, also run by `deploy-staging.yml` when a check fails after the machine changed) only updates every machine of the staging app to the previous image (`fly machine update`) and waits until every process is up. It does not run migrations (the release command is part of `fly deploy`, which a rollback does not call, and an older image cannot find a newer schema revision), nor a schema dump, grants, OCR, plugin, sign-in or click-walk step: migrations only add, so the older image runs on the newer schema, and the grants for the older commit are already applied.

## What `make release-pr` checks

| Check | Source | Refusal |
|---|---|---|
| `ci.yml` succeeded on the branch head | `gh run list --workflow ci.yml --commit <sha>` | Names the conclusion, or "no ci.yml run" |
| The staging deploy of that commit succeeded | The `staging / deploy` job of that `ci.yml` run, or the `deploy` job of a `deploy-staging.yml` run started by hand | Names the missing job or its conclusion |
| The click walk ran and had no failures | The job's log line `click walk (N OK, N FAIL)` from `deploy/fly/stg_deploy.sh`; a skipped walk or a failure refuses | Names the line |
| No PR from the branch is open | `gh pr list --base main --head <branch>` | Prints that PR and stops |

The use cases and the owner's click-through are not recorded in the repository, so the script cannot check them. A
branch is checked on every push (`ci.yml` lists `release/**` and `hotfix/**`), so each commit on it has a run; a
branch's first push compares with `origin/main`, so the first run covers the whole release.

The PR body lists the pull requests merged since main, breaking changes marked in commit messages (`!:` in a subject
or `BREAKING CHANGE` in a body), whether `sdk/**` changed, and the Python and TypeScript SDK versions on main and on
the branch.

## What each push or tag starts

| Event | Workflow | What it does |
|---|---|---|
| Push to `develop` | `ci.yml`, then `deploy-staging.yml` | Checks, then deploys develop to staging unless a release or hotfix branch exists or `STAGING_HOLD` is set |
| Push to `release/*` or `hotfix/*` | `ci.yml`, then `deploy-staging.yml` | Checks, then deploys that branch to staging with the click walk |
| PR into `main` | `ci.yml`, `codeql.yml` | The same checks as any pull request. `scorecard.yml` runs only when the PR changes workflows, Dockerfiles or `sdk/check.sh` |
| Merge into `main` | `release-tag.yml` | Runs `make release-tag`: tags the merge commit `vX.Y.Z` when its title names a `release/` or `hotfix/` branch (`scripts/release-tag.sh`), and pushes the tag. Any other push to main gets no tag. It then starts `sdk-publish.yml` and `release-images.yml` on the tag by `workflow_dispatch`, because a tag pushed with the workflow token starts no workflow itself |
| Tag `vX.Y.Z` | `sdk-publish.yml` | Builds, signs and attests both packages, and publishes a package only when its version is not on PyPI or npm yet. A published version cannot be reused, so raise the versions in `sdk/python/pyproject.toml` and `sdk/typescript/package.json` on the release branch. Without the repository variable `SDK_PUBLISH=1` and the `NPM_TOKEN` and `PYPI_TOKEN` secrets, every run is a dry run. A publish also makes a draft GitHub release per SDK. No branch push publishes |
| Tag `vX.Y.Z` | `release-images.yml` | Builds every image for linux/amd64 and linux/arm64 and pushes it to `ghcr.io/chanl-ai/ops-ai/<image>` |
| Merge into `main` | The docs site on Vercel (`docs/deploy/docs-site.md`) | Builds `apps/docs`. `ignoreCommand` in `apps/docs/vercel.json` skips a commit that changes none of `docs`, `services`, `apps/docs` and `pnpm-lock.yaml` |
| Merge into `main`, and weekly | `codeql.yml`, `scorecard.yml` | Code scanning, and the OpenSSF Scorecard (published to api.scorecard.dev from main) |

A merge to `main` does not touch staging.

## Version tags

Every release and hotfix is tagged `vX.Y.Z`; there is no second tag scheme. Installs from before this flow hold date
tags (`vYYYY-MM-DD.N`); `make version`, `make update-url` and `make update-download` accept both, and with no `TO=` they
pick the newest release on the releases feed whichever scheme it uses (`scripts/update_from_diff.sh`).

## Checks after the merge

| Check | Command |
|---|---|
| The version tag is on the merge commit | `git fetch --tags origin && git tag --points-at <merge commit>` shows `vX.Y.Z` |
| main's history is release merges only | `git log --first-parent --format=%s origin/main -5` |
| The npm version, when `sdk/**` changed and publishing is on | `npm view @chanl-ai/ops-ai version` equals the version in `sdk/typescript/package.json` |
| The PyPI version, same condition | `curl -sf https://pypi.org/pypi/ops-ai/<version>/json` answers; `<version>` is the one in `sdk/python/pyproject.toml` |
| The `sdk-publish` run | `gh run list --workflow sdk-publish.yml --limit 1`: success; "dry run" in its log means nothing was published |
| The images | `gh run list --workflow release-images.yml --limit 1`: success |
| The docs site is updated | The Vercel deployment for the merge commit is ready, or the site shows the changed page. A skipped build is correct when the merge changed no docs |
| Develop holds main | `git fetch origin && git rev-list --count origin/develop..origin/main` prints 0 after the back-merge; a count above 0 means the back-merge was squashed or not done |

## Branch protection to set

For the owner to apply in the repository settings; nothing here changes them.

| Rule | Setting |
|---|---|
| `main` ruleset, target | The default branch `main` |
| Pull request required | On, one approving review, stale approvals dismissed on a new push |
| Allowed merge methods | Merge commit only (squash and rebase off) |
| Source branches | Only `release/*` and `hotfix/*` may open a PR into `main`, plus the back-merge PR's own head, `main`, into `develop` |
| Required status checks | `ci-ok` |
| Linear history | Off: it forbids merge commits |
| Force pushes, deletion | Blocked |
| Tags `v*` | Creation limited to maintainers; update and deletion blocked |
| `develop` ruleset | Pull request required; merge commit allowed; the back-merge from `main` allowed |
| Auto-delete head branches | On, so merged `release/*` and `hotfix/*` branches go; keep them until the back-merge is merged |

GitHub rulesets have no source-branch condition. The source rule needs a status check that fails a PR into `main` whose
head branch is not `release/*` or `hotfix/*`; until one exists, the rule holds by convention.
