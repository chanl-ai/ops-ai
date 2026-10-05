# Rules for coding agents

Status: current.

| Rule | Detail |
|---|---|
| Read first | `CONTRIBUTING.md`, then `apps/console/CLAUDE.md` before changing console code |
| Verify | Run `pnpm verify` from the repo root before reporting work as done; it must pass |
| Fixtures | Demo data lives only in `apps/console/src/lib/api/mock/`. Never put fixtures in types, hooks, components or pages |
| Data flow | Pages read data through hooks; hooks call the API contract; components take props only |
| Docs | Follow the doc standards in `CONTRIBUTING.md`; update cross-references when a file moves |
| Hooks | Do not bypass the pre-commit hook with `--no-verify`; fix the cause |
| Secrets | Never add `.env` files, credentials or real customer data |
