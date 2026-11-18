# Releasing with gitflow

Status: current. `develop` takes every merged change. A release is cut from it as `release/X.Y.Z`, tested on staging,
merged into `main` with a merge commit, tagged `vX.Y.Z`, and merged back into `develop`. A fix to what is already on
`main` is a `hotfix/X.Y.Z` cut from `main` that follows the same path. `git log --first-parent main` then lists only
release and hotfix merge commits. The commands live in `scripts/release.py`; each make target only calls it, and every
one prints what it would do unless `DRY=0`.

## The flow

| Step | Who | Command or action |
|---|---|---|
| 1. Cut | Maintainer | `make release-cut V=X.Y.Z` (preview), then `DRY=0`: pushes `release/X.Y.Z` from `origin/develop` and deploys it to staging with `make stg-deploy-ci REF=release/X.Y.Z`, which starts `deploy-staging.yml` by hand with the click walk. For a hotfix, `make hotfix-cut V=X.Y.Z` does the same from `origin/main` |
| 2. Hold staging | Owner | Set the repository variable `STAGING_HOLD` to a reason (for example `release 1.2.0 under test`) so a merge to develop does not replace the release on staging. The workflow's own pin looks for an open PR from `develop` into `main`, which a release PR is not. Clear it after the merge |
| 3. Test staging | Maintainer, owner | The deploy's click walk, use cases against staging (`OPS_USECASE_BASE_URL=https://<staging host> make usecase-test UC=<id> LAYER=api`; only use cases marked safe run, see `docs/usecases/README.md`), and the owner's click-through. Only fixes go on the release branch |
| 4. Open the PR | Maintainer | `make release-pr V=X.Y.Z` (preview), then `DRY=0`: opens `release/X.Y.Z` into `main` titled `release: X.Y.Z (develop → main)` (`release: X.Y.Z (hotfix → main)` for a hotfix) |
| 5. Merge | Owner | A merge commit. No squash and no rebase, so main's first-parent history holds one commit per release |
| 6. Tag | Maintainer | `git tag vX.Y.Z <merge commit> && git push origin vX.Y.Z` on main's merge commit |
| 7. Back-merge | Maintainer | `make release-back-merge V=X.Y.Z` (preview), then `DRY=0`: opens `main` into `develop`; the owner merges it with a merge commit |

## What `make release-pr` checks

| Check | Source | Refusal |
|---|---|---|
| `ci.yml` succeeded on the branch head | `gh run list --workflow ci.yml --commit <sha>` | Names the conclusion, or "no ci.yml run" |
| `deploy-staging.yml` succeeded on that commit | `gh run list --workflow deploy-staging.yml --commit <sha>` | Names the missing run or its conclusion |
| The click walk ran and had no failures | The run's log line `click walk (N OK, N FAIL)` from `deploy/fly/stg_deploy.sh`; a skipped walk or a failure refuses | Names the line |
| No PR from the branch is open | `gh pr list --base main --head <branch>` | Prints that PR and stops |

The use cases and the owner's click-through are not recorded in the repository, so the script cannot check them.
`ci.yml` runs on pushes to `develop` and `main` and on pull requests, not on pushes to `release/*`. A release branch
with no commits beyond develop's head has the run develop's push made; a fix committed on the branch has no run until
a PR carries it, so the script refuses with "no ci.yml run" until one exists.

The PR body lists the pull requests merged since main, breaking changes marked in commit messages (`!:` in a subject
or `BREAKING CHANGE` in a body), whether `sdk/**` changed, and the Python and TypeScript SDK versions on main and on
the branch.

## What each push or tag starts

| Event | Workflow | What it does |
|---|---|---|
| Push to `release/*` or `hotfix/*` | Nothing | `ci.yml` and the others do not list these branches. The deploy to staging is started by hand |
| PR into `main` | `ci.yml`, `codeql.yml` | The same checks as any pull request. `scorecard.yml` runs only when the PR changes workflows, Dockerfiles or `sdk/check.sh` |
| Merge into `main` | `release-tag.yml` | Runs `make release-tag`: tags the merge commit `vYYYY-MM-DD.N` (UTC date, N counts that day's tags from 1) and pushes it. A commit that already has a date tag keeps it |
| Merge into `main` | `sdk-publish.yml`, when the merge changes `sdk/**` | Builds, signs and attests both packages, and publishes a package only when its version is not on PyPI or npm yet. A published version cannot be reused, so raise the versions in `sdk/python/pyproject.toml` and `sdk/typescript/package.json` on the release branch. Without the repository variable `SDK_PUBLISH=1` and the `NPM_TOKEN` and `PYPI_TOKEN` secrets, every run is a dry run. A publish also makes a draft GitHub release per SDK |
| Merge into `main` | The docs site on Vercel (`docs/deploy/docs-site.md`) | Builds `apps/docs`. `ignoreCommand` in `apps/docs/vercel.json` skips a commit that changes none of `docs`, `services`, `apps/docs` and `pnpm-lock.yaml` |
| Merge into `main`, and weekly | `codeql.yml`, `scorecard.yml` | Code scanning, and the OpenSSF Scorecard (published to api.scorecard.dev from main) |
| Tag `vX.Y.Z` | `release-images.yml` | Builds every image for linux/amd64 and linux/arm64 and pushes it to `ghcr.io/chanl-ai/ops-ai/<image>`. The date tag builds no images |
| Merge into `develop` (the back-merge) | `ci.yml`, then `deploy-staging.yml` | Deploys develop to staging again, unless `STAGING_HOLD` is set. Clear the hold first |

A merge to `main` does not touch staging.

## Checks after the merge

| Check | Command |
|---|---|
| The date tag and the version tag are on the merge commit | `git fetch --tags origin && git tag --points-at <merge commit>` shows `vYYYY-MM-DD.N` and `vX.Y.Z` |
| main's history is release merges only | `git log --first-parent --format=%s origin/main -5` |
| The npm version, when `sdk/**` changed and publishing is on | `npm view @chanl-ai/ops-ai version` equals the version in `sdk/typescript/package.json` |
| The PyPI version, same condition | `curl -sf https://pypi.org/pypi/ops-ai/<version>/json` answers; `<version>` is the one in `sdk/python/pyproject.toml` |
| The `sdk-publish` run | `gh run list --workflow sdk-publish.yml --branch main --limit 1`: success; "dry run" in its log means nothing was published |
| The images, after the version tag | `gh run list --workflow release-images.yml --limit 1`: success |
| The docs site is updated | The Vercel deployment for the merge commit is ready, or the site shows the changed page. A skipped build is correct when the merge changed no docs |
| Develop holds main | `git fetch origin && git rev-list --count origin/develop..origin/main` prints 0 after the back-merge |

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
