---
name: ops-usecase
description: Find, run and write an end-to-end use case (docs/usecases) at the api, sdk, cli or ui layer. Use when someone asks to prove a change end to end, run a use case, or add one.
agent: agent
---

# ops-usecase: write and run a use case

<!-- Generated from `docs/guide/skills/ops-usecase.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make usecase-list, make usecase-show, make usecase-test, make usecase-new, make usecase-coverage.

## When to use it

Every change needs a path a client can drive, run once and seen red before it is green. The full rules are in
`docs/usecases/README.md`; Claude Code's `usecase` skill covers the same ground in more depth.

## Steps

1. `make usecase-list` lists the registry; `make usecase-show UC=<id>` shows one and its scripts.
2. `make usecase-test UC=<id> LAYER=api` runs one on its own stack (needs `make db-up`); `LAYER=ui` drives the console
   in a browser.
3. A new one: `make usecase-new SERVICE=<service> TITLE="<title>"`, then write the steps table and the script under
   `docs/usecases/<service>/scripts/`. Drive only what a client can drive; never reach into a database.
4. Run it before the change exists and keep the red output, then make it pass.

## Proof

```bash proof
make usecase-list
make usecase-show UC=uc-531
make usecase-test UC=uc-531 LAYER=api
```
