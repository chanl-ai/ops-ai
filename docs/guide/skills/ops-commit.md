# ops-commit: pass the commit checks with a What's new entry

Status: current. Proven by `make skills-proof` (c-554).

skill: ops-commit
description: Get a change through Ops AI's commit checks: the console and docs checks, the Python verify, a What's new entry for a person using the console, and a commit message that says what was wrong and how it was proven. Use before committing or when the pre-commit hook fails.
targets: make verify, make changelog-verify, make docs-verify, pnpm verify

## When to use it

A change is ready to commit, or the pre-commit hook refused it.

## Steps

1. `pnpm verify` is the pre-commit hook: the console's types and standards and the docs check. Never skip it with
   `--no-verify`; fix the cause.
2. `make verify` runs everything a commit must pass, on the scripted model.
3. A change a person would notice gets a What's new entry in `changelog/` (one JSON file), written for someone using
   the console; `make changelog-verify` checks its words.
4. Docs live only under `docs/`, each with a status line and listed in `docs/README.md`; `make docs-verify` checks it.
5. The commit message: `type(scope): subject`, then what was wrong and what was run to prove the fix
   (`CONTRIBUTING.md`).

## Proof

```bash proof
make changelog-verify
make docs-verify
```
