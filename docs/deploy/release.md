# Releasing

Status: current. One flow, git flow: feature pull requests merge into `develop` through the merge queue; a release is a
`release/X.Y.Z` branch cut from `develop`, tested on staging, merged into `main` by one pull request, tagged `vX.Y.Z`
and merged back into `develop`. A hotfix is the same from the newest tag as `hotfix/<what>`. What runs on which event is
in [Delivery](../architecture/delivery.md); this page is the release. `make release-doctor` checks the flow stays one
path (`LIVE=1` also reads GitHub).

## The five steps

| Step | Who | Command | What fires |
|---|---|---|---|
| 1. Start | Maintainer | `make release-start V=X.Y.Z` (preview), then `DRY=0` | Pushes `release/X.Y.Z` from develop's tip with one commit that sets `deploy/release/version`, both SDK versions and the folded changelog, and opens the pull request `release: X.Y.Z` into `main`. Refuses while another `release/*` or `hotfix/*` exists, when `vX.Y.Z` exists or is not above the newest tag, or when develop's tip has no green run. A hotfix: `make hotfix-start V=X.Y.Z NAME=<what>` from the newest tag |
| 2. Test | Automatic | none | The push runs every job of `ci.yml`, `release-security.yml`, `codeql.yml` and the staging deploy with its click walk. The pull request into `main` starts no second run: its `ci-ok` waits for the push run's result. A fix is a pull request into the release branch: it runs only the leak scan, and its merge push runs every job again |
| 3. Candidate | Maintainer | `make release-rc` (preview), then `DRY=0` | Tags the branch tip `vX.Y.Z-rc.N` once its staging deploy and walk passed and prints the staging address. An rc tag publishes nothing |
| 4. Finish | Owner | Click merge on the pull request | `release-finish.yml` tags the merge commit `vX.Y.Z` (the version in `deploy/release/version` on `main`; it refuses when the branch name differs), starts `sdk-publish.yml` and `release-images.yml` on the tag, opens the merge-back pull request into `develop` and arms auto-merge so it enters the queue by itself, and deletes the release branch |
| 5. Merge-back | Automatic | none | The merge-back changes nothing or only the version fields and the changelog, so it runs no CodeQL, no leak scan and no test job (`scripts/ci_trivial.py` reads the diff, not the branch name) and is green in about a minute |

While a `release/*` or `hotfix/*` branch exists, a push to `develop` still runs its checks and the staging job is skipped
with a notice naming the branch, so the candidate on staging is not overwritten. The branch's deletion ends the freeze.

## Versions and tags

| Name | Meaning |
|---|---|
| `deploy/release/version` | The version a checkout installs; equals both SDK versions on every branch (`make release-doctor`) |
| `vX.Y.Z` | The merge commit on `main`. Starts SDK publishing and image builds. Never moved |
| `vX.Y.Z-rc.N` | A candidate on the release branch. Publishes nothing |

## When something is stuck

| Symptom | Command |
|---|---|
| The pull request merged but there is no tag, merge-back or deleted branch | `gh workflow run release-finish.yml -f branch=release/X.Y.Z`; a rerun keeps a tag that already exists |
| The merge-back pull request exists but is not armed | `gh pr merge --auto --merge <number>` |
| The merge-back conflicts (label `needs-merge`) | Merge `origin/develop` into `merge-back/<branch>` by hand and push, never a rebase |
| `main` has a release `develop` lacks | `gh workflow run release-finish.yml -f branch=<the merged branch>` opens the merge-back |
| Staging shows the wrong build | `make stg-deploy-ci REF=release/X.Y.Z`; `STAGING_HOLD` and the freeze are in [Staging](fly-staging.md) |
| `release-start` refuses | The message names the reason: another branch, an existing tag, a version not above the newest tag, or a red develop tip |
| The tag push worked but nothing published | `gh workflow run sdk-publish.yml --ref vX.Y.Z` and `release-images.yml` the same way |
| A hotfix must also reach the open release | Merge `origin/main` into the release branch with a pull request into it |

## Checks

`make release-doctor` runs in `make checks`: no guide, workflow, target or agent file names a removed path (a step of the
old flows); `deploy/release/version` equals both SDK versions; this page
lists exactly the release targets that exist. With `LIVE=1` (the release manager's tick) it also reads GitHub: at most
one release or hotfix branch, matching its version file; the newest tag is on `main`; `develop` holds `main`; no
merge-back pull request is unarmed. Each failure prints one line and the command that fixes it.

The release package a client installs is built from the tag: [Release package](release-package.md).
