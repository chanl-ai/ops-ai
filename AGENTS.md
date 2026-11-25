# Rules for coding agents

Status: current.

Every change to `services/`, `packages/` or `apps/console/` follows `docs/architecture/engineering-standards.md`,
which names the rule each check enforces. Every folder has a `CLAUDE.md` saying what it owns and how to run, test and
lint it; the index is the "Folder guides" section of `CLAUDE.md`. Read the guide for the folder you change.

## Branches, pull requests and commits

| Rule | Detail |
|---|---|
| Branch name | `<type>/<scope>-<what-changed>`. Types: feat, fix, chore, docs, refactor, perf, test, ci. Never wip, tmp, new, v2, fixes, updates, changes, cleanup or feedback in a name |
| Target | Every pull request targets the release train `release/current` (`release/1.1.0` until it is renamed), never `develop` or `main`. Never queue a PR, merge it or set auto-merge (`docs/deploy/release.md`) |
| One slice | A change is the whole slice in one PR: server, SDK in both languages, CLI and screen |
| Commits | `type(scope): subject` under 72 characters, body of at most 3 lines. A `fix` commit carries a `Siblings:` trailer. `commit-message-check.mjs` enforces this. Never `--no-verify`, stash or force push |
| Verify | Run `pnpm verify` from the repo root before reporting work as done; it must pass |

## Code and tests

| Rule | Detail |
|---|---|
| No client joins | No joining, counting or summing in the client; the API returns joined data (`UI1`). Pages read data through hooks, hooks call the API contract, components take props only |
| Access and boundaries | Every access decision goes through `can()` (`AC1`); a Pydantic model at every boundary (`MD1`, `MD4`) |
| Tests | Name the failure modes first, then write one test per mode. At most 5 tests for a small change, 10 for a medium one, 15 for a large one. Assert behaviour through the public seam. Mock only the outside world. Revert the fix once and watch each test fail |
| Run less | Run only the tests you touch: `make test PKG=... T=...` and `make usecase-test UC=... LAYER=...` |
| Python | The Python SDK supports Python 3.11. Do not use 3.12-only syntax such as `class X[T]` |
| Fixtures | Demo data lives only in `apps/console/src/lib/api/mock/`. Never put fixtures in types, hooks, components or pages |
| Docs | Follow the doc standards in `CONTRIBUTING.md`; update cross-references when a file moves |

## This repository is public

| Rule | Detail |
|---|---|
| Trailers and links | No co-author or vendor trailers, no links to agent sessions or agent web UIs |
| Names | No internal hosts, no names of people or clients, no tracker ids, board slices or private paths in code, comments, docs, commits or PR text |
| Secrets | Never commit `.env`, credentials or real customer data; `.env.example` is the only env file in git |
| Checks | `scripts/leak_scan.py` and `scripts/check-public-paths.mjs` enforce the above; see "Everything here is public" in `CONTRIBUTING.md` |
