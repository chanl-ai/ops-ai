# Rules for coding agents

Status: current.

| Rule | Detail |
|---|---|
| Read first | `CONTRIBUTING.md`; `apps/console/CLAUDE.md` before changing console code; `docs/README.md` for the design behind a change |
| Verify | Run `pnpm verify` from the repo root before reporting work as done; it must pass |
| Fixtures | Demo data lives only in `apps/console/src/lib/api/mock/`. Never put fixtures in types, hooks, components or pages |
| Data flow | Pages read data through hooks; hooks call the API contract; components take props only |
| Docs | Follow the doc standards in `CONTRIBUTING.md`; update cross-references when a file moves |
| Hooks | Do not bypass the pre-commit hook with `--no-verify`; fix the cause |
| Secrets | Never commit `.env`, credentials or real customer data; `.env.example` is the only env file in git |
| Names in code | A name or comment says what the thing is. Do not cite a card id (`c-631`), a board slice (`A2`, `W1`, `R7`) or a path into the private planning board. A public checkout does not have the board; the reader has to understand the code without it |
