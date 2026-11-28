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
| 2. Take in | `ops-release` agent | `make release-intake` (below) merges each finished pull request into the train with its own merge commit, merges `develop` in when it moves, runs `ci-local` and pushes when green; the agent resolves the conflicts and reds it reports |
| 3. Try on staging | Owner | After telling the owner, `make stg-deploy-ci REF=release/current` deploys the train by hand. A push to the train deploys nothing; the owner sets `STAGING_HOLD` while trying it. Only fixes go on the train |
| 4. Version | Maintainer | `make release-version V=X.Y.Z` (preview), then `DRY=0`: one commit on the train that sets `deploy/release/version` and folds the changelog fragments into `changelog/releases/X.Y.Z.json`. `release-pr` refuses when the file says anything else |
| 5. Open the PR | Maintainer | In a checkout at the train's head, `make release-pr V=X.Y.Z` (preview), then `DRY=0`: runs `make ci-local`, then opens `release/current` into `develop` titled `release: X.Y.Z into develop` |
| 6. Queue | Owner | Queues the pull request after approving it. A push to it while queued drops it from the queue, so the train stays frozen until it lands. The queue merges with a merge commit |
| 7. Tag | Automatic | `release-tag.yml` runs after `ci.yml` finishes on a push to `develop`, and only when that run's staging deploy and click walk passed (or a person starts it with `walk_passed` set); `scripts/release-tag.sh` refuses to push on GitHub without `WALK_PASSED=1`. When the merge subject, or the first body line of the merge commit, is `release: X.Y.Z into develop`, it tags that commit `vX.Y.Z`; otherwise a `feat` merge is the next minor version, a `fix` or `perf` merge the next patch, and any other type gets no tag |
| 8. Move main | Automatic | The same job runs `scripts/release-main.sh`: `git push origin <sha>:main`, which git refuses unless it is a fast-forward. With the deploy key the push passes; without it the job stops red and prints the owner's one command (below) |
| 9. Publish | Automatic | The same job starts `sdk-publish.yml` and `release-images.yml` on the tag, since a tag pushed with the workflow token starts no workflow itself |
| 10. Next train | Maintainer | `make release-cut` (preview), then `DRY=0`: fast-forwards `release/current` to `origin/develop`, or creates it when missing. It refuses when the train holds commits develop lacks |

## Taking pull requests in: `make release-intake`

One command does the mechanical work of step 2; a person or agent is needed only for a logic conflict or a red test.
`DRY=1` (the default) prints the plan and changes nothing on the remote; `DRY=0` acts. `TRAIN` defaults to `release/current`
when it exists, else `release/1.1.0`; `PRS=1,2` picks and orders the pull requests (default: oldest first).

| Step | What it does |
|---|---|
| Stock | Lists open pull requests. Left alone, with the reason in the report: the release pull request, dependabot, drafts, a base other than develop or the train |
| Retarget | `gh api -X PATCH .../pulls/N -f base=<train>`. GitHub's refusals "no new commits between" (already in the train) and "added to a merge queue" skip that pull request; they are not failures. Runs the old base started are cancelled, never a merge-queue run |
| Merge | In a worktree `ops-ai-worktrees/intake-<train>` (`INTAKE_DIR`): develop first, then each branch with its own `--no-ff` merge commit. A branch already in the train is skipped |
| Mechanical conflicts | Generated openapi and SDK files take our side and `make openapi` rewrites them; `deploy/database/golden/mssql` by `make db-ddl-golden`; `uv.lock` and `docs/architecture/dependencies.md` by `uv lock` and `make sbom`; `pnpm-lock.yaml` by `pnpm install --lockfile-only`; `roadmap.json`, `changelog/*.json` lists and `api-changes.md` keep both sides; two Alembic heads are joined by pointing the merged chain's first revision at the train's head. Any other conflict aborts that one merge, is recorded with its files, and the run goes on with the next pull request |
| Prove | `make ci-local OUT=<dir>/ci-local.json` in the worktree |
| Push | A plain push of the result, only when `ci-local` is green. The release pull request body is rebuilt |
| Report | `REPORT` (default `.run/release-intake/<time>/report.json`): merged, skipped with reason, conflicts with files, red jobs with failing test ids and the last log lines, the worktree left for a person |

Exit 0 is green, 1 is a red job or a refused push, 2 is a conflict a person has to resolve. After exit 1 or 2 the worktree
is kept: fix and commit there, then `make release-intake RERUN=<report.json>` runs only the red jobs (the others are
carried over from the report), pushes when green and removes the worktree; `RESUME=1` does the same with a full
`ci-local`, after a conflicting pull request was merged by hand in that worktree.

`make ci-local` takes the same options for the branch tester and the epic driver: `OUT=<file>.json` writes each job's
status, seconds, failing test ids, log and the last lines of a red one; `JOB=a,b` names jobs or table labels;
`RERUN=<file>.json` runs only that report's red jobs; `SHARDS=n SHARD=i` runs every nth planned job (one machine per
shard); `UCS="uc-013:ui uc-607:api"` adds use cases to the plan as jobs of their own (`make usecase-test`, so its slot
guard applies).

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

The check on the train is `make ci-local`, not a staging deploy by hand. A pull request into `release/**` runs no CI, so a check
has to run before the push, and `ci-local` runs the jobs the merge queue will run, on the same commit, in the maintainer's
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
| Pull request into `release/**` | None | `ci.yml` does not run; the push that follows the merge does |
| Pull request into `develop` or `main`, merge queue entry | `ci.yml`, `codeql.yml` | The checks; the queue tests the pull request on develop's tip and merges only on green, so a branch behind develop is not rebuilt until it queues. `scorecard.yml` runs only when the pull request changes workflows, Dockerfiles or `sdk/check.sh` |
| Push to `develop` | `ci.yml`, then `deploy-staging.yml`; `release-tag.yml` after a green staging walk | Checks (none when a green merge queue run already tested that commit), then a deploy to staging unless a numbered `release/X.Y.Z` or a `hotfix/*` branch exists or `STAGING_HOLD` is set. `release-tag.yml` tags a release merge and moves `main` |
| A merge queue run of `ci.yml` finishes | `queue-retry.yml` | First failure: reruns the failed jobs. Second failure: comments each failed job and its first error line on the pull request. A green rerun queues the pull request again |
| A `release/*` or `hotfix/*` pull request merges into `main` | `merge-back.yml` | Opens `merge-back/<name>` (cut from main, develop merged in) into develop with auto-merge on |
| Push to `release/X.Y.Z` or `hotfix/**` | `ci.yml`, then `deploy-staging.yml`, then the web scan; `release-security.yml`; `codeql.yml` | Checks in full whatever changed, then deploys that branch with the click walk and runs an OWASP ZAP baseline scan of staging (report only: the report is an artifact and a warning does not fail the job). `release-security.yml` audits dependencies and licences, checks the SBOM, and builds, scans and signs every image in a registry inside the runner |
| Tag `vX.Y.Z` | `sdk-publish.yml` | Builds, signs and attests both packages, and publishes a package only when its version is not on PyPI or npm yet. A published version cannot be reused, so raise the versions in `sdk/python/pyproject.toml` and `sdk/typescript/package.json` on the train. Without the repository variable `SDK_PUBLISH=1` and the `NPM_TOKEN` and `PYPI_TOKEN` secrets, every run is a dry run |
| Tag `vX.Y.Z` | `release-images.yml` | Builds every image for linux/amd64 and linux/arm64 and pushes it to `ghcr.io/chanl-ai/ops-ai/<image>` |
| `main` moves | The docs site on Vercel (`docs/deploy/docs-site.md`); `codeql.yml`, `scorecard.yml` | Builds `apps/docs`, skipped when none of `docs`, `services`, `apps/docs` and `pnpm-lock.yaml` changed; code scanning and the OpenSSF Scorecard |

A move of `main` does not touch staging.

## Branch automation

Heavy runs happen on GitHub Actions, never on a laptop. A builder runs the tests of the files touched and pushes.

| Need | What does it |
|---|---|
| The full `make verify` on a branch | `make gha-verify BRANCH=x` starts `verify-full.yml` there, watches it and prints the first error line of each failed job |
| The queue takes only what is ready | `ci.yml` job `ready` fails when CodeQL is red or another job is red; `ci-ok`, the one required check, needs it |
| Generated OpenAPI documents and SDK files | `ci.yml` job `generated` runs `make openapi` on the pull request; `generated-commit` pushes any difference to its branch. Not for a fork, never in the queue |
| A red queue run | `queue-retry.yml`: one rerun of the failed jobs, then a comment with each failed job's first error line. A flaky use case is quarantined in `config/quarantine.json` and does not fail the run |
| A fix pushed to a queued pull request | `make requeue PR=n` takes it out of the queue and queues it again at the end |
| A new lane of work | `make lane BRANCH=x`: a worktree off `origin/develop` with the main checkout's `.venv` and `node_modules` linked in |
| Release and hotfix branches return to develop | `merge-back.yml`, after the merge into main |

`generated-commit` and `merge-back.yml` push over the write deploy key (`.github/actions/push-key`),
because a push made with the workflow token starts no checks. Without the key they push with the token and warn that
the pushed commit will have no `ci-ok`.

The sections above on the train (`release-intake`, `release-pr`, `release-tag`) describe a release that returns to
develop first and is tagged there. Status: being replaced by a `release/X.Y.Z` branch that merges into main; those
targets still work as written until they are changed.

## First run of the tag and nightly workflows

GitHub starts a `workflow_run` or `schedule` workflow only from the copy on the default branch. While `main` holds the
old push-triggered tag file and no `nightly-usecases.yml`, neither new workflow starts by itself, and the tag step does
not run after a develop merge. Until the next move of `main` carries them:

| Step | How |
|---|---|
| Get the files onto `main` | The next release pull request into `main` carries them; to start sooner, a pull request that changes only these workflow files into `main` |
| Tag a develop commit meanwhile | After its staging walk passed, an admin runs `gh workflow run release-tag.yml --ref main -f ref=<sha> -f walk_passed=true`; the workflow runs from `main`'s copy, so this works only once the file is there. Before that, run `DRY=1 make release-tag REF=<sha>` and then `make release-tag REF=<sha>` by hand, with `BUMP=auto` for a queue merge |
| Run the nightly once | `gh workflow run nightly-usecases.yml --ref develop` after the file is on `main` |

A `walk_passed=true` dispatch counts only from a repository admin; a writer's dispatch is ignored with a warning.

## The staging hold

`STAGING_HOLD` (repository variable) keeps develop merges off staging while a release is under test. Its value is
`X.Y.Z: reason`, for example `1.1.0: under test on staging`.

| Case | Result |
|---|---|
| The hold is set and tag `vX.Y.Z` does not exist | The deploy is skipped and the `staging` job fails red, with the hold text in the error, so a green run always means deployed |
| Tag `vX.Y.Z` exists | The hold is stale: it is ignored, the deploy goes on and a notice says to clear the variable |
| The value has no `X.Y.Z:` prefix | Refused as invalid, the job fails red |
| A numbered `release/X.Y.Z` or a `hotfix/*` branch exists on origin | Freezes develop merges the same way: the deploy is skipped and the job fails red with the branch names |
| A hand-started run | Overrides the hold and the freeze, as before; the summary says so |

A release or hotfix branch whose head is already an ancestor of the deployed commit protects nothing, so it does not freeze staging (a notice names it); a head the runner cannot read keeps the freeze. The rule is `scripts/staging_hold.py`, which `deploy-staging.yml` calls; `scripts/tests/test_staging_hold.py` proves it.

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
