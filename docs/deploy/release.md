# Releasing from the train

Status: current (owner decision, 2026-11-22). One branch, `release/current`, collects every finished feature pull
request and is never deleted. One pull request, `release: X.Y.Z into develop`, takes it through develop's merge queue,
the develop merge commit is tagged `vX.Y.Z`, and `main` fast-forwards to that tag. `main` and `develop` then hold the
same commits, so there is no pull request to `main` and no back-merge. The commands live in `scripts/release.py`,
`scripts/release-tag.sh` and `scripts/release-main.sh`; each make target only calls one, and the ones that change
something print what they would do unless `DRY=0`.

## The flow

| Step | Who | What happens |
|---|---|---|
| 1. Build | Builder | A feature pull request targets `release/current`. CI does not run on a pull request into it or a push to it (`ci.yml`), so a builder runs only the tests it touches |
| 2. Take in | `ops-release` agent | Merges each finished pull request into the train with its own merge commit, merges `develop` in when it moves, fixes red tests on the train |
| 3. Try on staging | Owner | After telling the owner, `make stg-deploy-ci REF=release/current` deploys the train by hand. A push to the train deploys nothing; the owner sets `STAGING_HOLD` while trying it. Only fixes go on the train |
| 4. Version | Maintainer | `make release-version V=X.Y.Z` (preview), then `DRY=0`: one commit on the train that sets `deploy/release/version`. `release-pr` refuses when the file says anything else |
| 5. Open the PR | Maintainer | In a checkout at the train's head, `make release-pr V=X.Y.Z` (preview), then `DRY=0`: runs `make ci-local`, then opens `release/current` into `develop` titled `release: X.Y.Z into develop` |
| 6. Queue | Owner | Queues the pull request after approving it. A push to it while queued drops it from the queue, so the train stays frozen until it lands. The queue merges with a merge commit |
| 7. Tag | Automatic | `release-tag.yml` runs on the push to `develop`. When the merge subject, or the first body line of the merge commit, is `release: X.Y.Z into develop`, it tags that commit `vX.Y.Z` |
| 8. Move main | Automatic | The same job runs `scripts/release-main.sh`: `git push origin <sha>:main`, which git refuses unless it is a fast-forward. With the deploy key the push passes; without it the job stops red and prints the owner's one command (below) |
| 9. Publish | Automatic | The same job starts `sdk-publish.yml` and `release-images.yml` on the tag, since a tag pushed with the workflow token starts no workflow itself |
| 10. Next train | Maintainer | `make release-cut` (preview), then `DRY=0`: fast-forwards `release/current` to `origin/develop`, or creates it when missing. It refuses when the train holds commits develop lacks |

## Hotfix

| Step | Command or action |
|---|---|
| Cut | `make hotfix-cut V=X.Y.Z HOTFIX=<what>`, then `DRY=0`: pushes `hotfix/<what>` from the newest `vX.Y.Z` tag (`FROM=<tag>` names another) with one commit on top that sets the version file to the new version |
| Fix | Commits on the hotfix branch. A push to `hotfix/**` still runs `ci.yml` in full and then deploys staging with the click walk, and staging is frozen for other merges while the branch exists |
| Open the PR | `make release-pr V=X.Y.Z HOTFIX=<what>`: needs `ci.yml` and the staging deploy with its click walk green on the head (the checks below), and opens `hotfix/<what>` into `develop` titled `hotfix: X.Y.Z into develop` |
| Ship | The same queue, tag and `main` fast-forward as a release. The train merges `develop` in afterwards |

## What `make release-pr` checks

| Check | Train | Hotfix | Refusal |
|---|---|---|---|
| `deploy/release/version` says `X.Y.Z` on the branch head | Yes | Yes | Names the file and the fix, `make release-version` |
| `develop` is merged into the branch | Yes | No (cut from a tag, so develop is ahead) | Says to merge develop in |
| The checkout is at `origin/<branch>` and clean | Yes | No | Names both commits, or says to commit |
| `make ci-local` is green on the head | Yes | No | Says it is red; the logs are in `.run/ci-local/` |
| `ci.yml` succeeded on the head | No | Yes | Names the conclusion, or "no ci.yml run" |
| The staging deploy of that commit succeeded, with a click walk and no failures | No | Yes | Names the missing job, its conclusion or the log line |
| No pull request from the branch is open | Yes | Yes | Prints that pull request and stops |
| The branch has something `origin/develop` lacks | Yes | Yes | Says so |

The check on the train is `make ci-local`, not a staging deploy by hand. Pushes to `release/**` run no CI, so a check
has to run somewhere, and `ci-local` runs the jobs the merge queue will run, on the same commit, in the maintainer's
checkout. It needs no owner approval, no wait for staging, and does not touch the shared app. The staging deploy is
still the owner's way to try the release by hand (step 3), but it is not recorded anywhere a script can read. A preview
(`DRY=1`) does not run `ci-local`.

The PR body lists the pull requests merged since develop, breaking changes marked in commit messages (`!:` in a subject
or `BREAKING CHANGE` in a body), whether `sdk/**` changed, and the Python and TypeScript SDK versions on develop and on
the branch. The queue runs the full CI once for the release; a release-proof job checks the version file on a
`release/X.Y.Z` branch.

The install proof in `release-proof` runs before the tag, when the release's images are not on ghcr.io yet, so it builds
them from the commit into a registry inside the runner (`make install-proof BUILD=1`). The pull from ghcr.io is a check
after the tag, below. Upgrades from a release before 874530fa use the online path (migrations at start-up), not the
offline SQL; `docs/deploy/database.md` explains why.

## The deploy key that moves main

`main` is protected by ruleset 27865407: no deletion, no force push, a pull request required, `scan` and `ci-ok`
required. GitHub does not accept the Actions app as a bypass actor, so the workflow token cannot push to `main`. A
write deploy key can bypass the ruleset, and the workflow pushes over SSH with it. The owner sets it up once:

| Step | Command |
|---|---|
| Make the key | `ssh-keygen -t ed25519 -N '' -f k` |
| Register it with write access | `gh repo deploy-key add k.pub --allow-write -t release-main` |
| Store the private half | `gh secret set RELEASE_MAIN_DEPLOY_KEY < k` |
| Remove the files | `rm k k.pub` |

The deploy key must be listed as a bypass actor in the `main` ruleset. The push is still plain, so git refuses
anything that is not a fast-forward, and the script never forces.

| Case | Result |
|---|---|
| The secret is set | The job pushes `<sha>:main` over SSH to `git@github.com:<repo>.git`, trusting GitHub's published host keys |
| The secret is missing, or the key is not allowed to bypass | The push is refused, the job stops red and prints `git push origin <sha>:main`, the one command the owner runs. Re-running the job then skips the tag and `main` and starts the publish and the image build |
| `main` is not an ancestor of the commit | Exit 1, nothing pushed |

## What each push or tag starts

| Event | Workflow | What it does |
|---|---|---|
| Pull request into `release/**`, push to `release/**` | None | `ci.yml` does not run |
| Pull request into `develop` or `main`, merge queue entry | `ci.yml`, `codeql.yml` | The checks; the queue merges only on green. `scorecard.yml` runs only when the pull request changes workflows, Dockerfiles or `sdk/check.sh` |
| Push to `develop` | `ci.yml`, then `deploy-staging.yml`; `release-tag.yml` | Checks, then a deploy to staging unless a numbered `release/X.Y.Z` or a `hotfix/*` branch exists or `STAGING_HOLD` is set. `release-tag.yml` tags a release merge and moves `main` |
| Push to `hotfix/**` | `ci.yml`, then `deploy-staging.yml` | Checks in full whatever changed, then deploys that branch with the click walk |
| Tag `vX.Y.Z` | `sdk-publish.yml` | Builds, signs and attests both packages, and publishes a package only when its version is not on PyPI or npm yet. A published version cannot be reused, so raise the versions in `sdk/python/pyproject.toml` and `sdk/typescript/package.json` on the train. Without the repository variable `SDK_PUBLISH=1` and the `NPM_TOKEN` and `PYPI_TOKEN` secrets, every run is a dry run |
| Tag `vX.Y.Z` | `release-images.yml` | Builds every image for linux/amd64 and linux/arm64 and pushes it to `ghcr.io/chanl-ai/ops-ai/<image>` |
| `main` moves | The docs site on Vercel (`docs/deploy/docs-site.md`); `codeql.yml`, `scorecard.yml` | Builds `apps/docs`, skipped when none of `docs`, `services`, `apps/docs` and `pnpm-lock.yaml` changed; code scanning and the OpenSSF Scorecard |

A move of `main` does not touch staging.

## Version tags

Every release and hotfix is tagged `vX.Y.Z`; there is no second tag scheme. Installs from before this flow hold date
tags (`vYYYY-MM-DD.N`); `make version`, `make update-url` and `make update-download` accept both, and with no `TO=` they
pick the newest release on the releases feed whichever scheme it uses (`scripts/update_from_diff.sh`).

## Checks after the merge

| Check | Command |
|---|---|
| The version tag is on the develop merge commit | `git fetch --tags origin && git tag --points-at origin/develop` shows `vX.Y.Z` |
| `main` equals the tag | `git rev-parse origin/main vX.Y.Z^{commit}` prints one commit twice |
| `develop` holds `main` | `git rev-list --count origin/develop..origin/main` prints 0, and `origin/main..origin/develop` prints 0 |
| The npm version, when `sdk/**` changed and publishing is on | `npm view @chanl-ai/ops-ai version` equals the version in `sdk/typescript/package.json` |
| The PyPI version, same condition | `curl -sf https://pypi.org/pypi/ops-ai/<version>/json` answers; `<version>` is the one in `sdk/python/pyproject.toml` |
| The `sdk-publish` run | `gh run list --workflow sdk-publish.yml --limit 1`: success; "dry run" in its log means nothing was published |
| The images | `gh run list --workflow release-images.yml --limit 1`: success |
| The published images install | Signed in to ghcr.io with a token that can read packages, `SIGNED_IN=1 make install-proof REF=vX.Y.Z` passes. The packages are private, so a pull without a login answers 403; a public pull needs the `ghcr.io/chanl-ai/ops-ai/*` packages made public, which is the owner's setting |
| The docs site is updated | The Vercel deployment for the new `main` commit is ready, or the site shows the changed page. A skipped build is correct when nothing in the docs changed |
| The next train exists | `make release-cut` (preview) says `release/current` is already at `origin/develop` after `DRY=0` ran |

## Branch protection to set

For the owner to apply in the repository settings; nothing here changes them.

| Rule | Setting |
|---|---|
| `develop` ruleset (27847271) | Merge queue on, merge method merge commit. A release pull request needs no other rule |
| `main` | Ruleset 27865407: no deletion, no force, pull request required, `scan` and `ci-ok` required, the `release-main` deploy key bypasses it (section above) |
| Tags `v*` | Creation limited to maintainers; update and deletion blocked |
| `release/current` and `release/1.1.0` | Ruleset 27865389 blocks deleting and force-pushing them: open pull requests would go back to `develop` if the train were deleted |
| Auto-delete head branches | Today on, which deletes `release/current` when the release pull request merges and sends every open pull request into it back to `develop`. Turn it off, or protect `release/current`; `make release-cut` recreates a missing train but cannot retarget pull requests |
