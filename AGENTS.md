# Rules for coding agents

Status: current.

Every folder has a `CLAUDE.md` saying what it owns and how to run, test and lint it from there; the index is the
"Folder guides" section of `CLAUDE.md`, and the rules every folder shares (onion order, one local stack, calling the
API as a person, tests, commits) are its "Working in one folder" section. Read the guide for the folder you change.
The table below holds for every change.

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
