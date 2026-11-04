# Rules for coding agents

Status: current.

| Rule | Detail |
|---|---|
| Read first | `CONTRIBUTING.md`; `apps/console/CLAUDE.md` before changing console code; `docs/README.md` for the design behind a change |
| Verify | Run `pnpm verify` from the repo root before reporting work as done; it must pass |
| Fixtures | Demo data lives only in `apps/console/src/lib/api/mock/`. Never put fixtures in types, hooks, components or pages |
| Data flow | Pages read data through hooks; hooks call the API contract; components take props only |
| Docs | Follow the doc standards in `CONTRIBUTING.md`; update cross-references when a file moves |
| Branches | Work on a branch and open a PR (`CONTRIBUTING.md`); never `--no-verify`, a stash or a push to `main` |
| Secrets | Never commit `.env`, credentials or real customer data; `.env.example` is the only env file in git |
| Names in code | A name or comment says what the thing is, never a tracker id, a board slice (`A2`) or a private path; readers have only this repo |
