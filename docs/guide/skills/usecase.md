# usecase: list, add, update and run the stories a person can do

Status: current. Proven by `make skills-proof`.

skill: usecase
description: List, add, update and run end-to-end use cases (docs/usecases) as plain user stories at the api, sdk or cli layer. Use when someone asks to prove a change end to end, says which stories work, or types /usecase list|add|update|run.
targets: make usecase-list, make usecase-add, make usecase-update, make usecase-run, make usecase-index

## What a use case is

A use case is a few plain stories that work, such as "A team admin connects Salesforce and runs Test connection".
Each story has a layer (sdk is the Python or TypeScript SDK, cli is a command a person types, api is the HTTP routes,
ui is the console), numbered steps, and the one step whose check proves it. The registry and rules are in
`docs/usecases/README.md`; the generated index is `docs/usecases/index.md`.

## The four routes

Each route is one command. Run it, then say what it printed in a few plain lines.

| Route | Run | What you get |
|---|---|---|
| `/usecase list [area]` | `make usecase-list AREA=<area>` | Every use case: id, short title, area, the layers that have a script, and each layer's last recorded run (`api ok`, `ui FAILED`, or `not run`). Area is a service name, with or without `-service` (`agents`). |
| `/usecase add <area> "<short title>"` | `make usecase-add AREA=<area> TITLE="<short title>"` | The next id, the page, one script stub per layer, the registry row and a rebuilt index. Add `LAYERS=api,sdk,cli` for more than api. |
| `/usecase update <id>` | `make usecase-update UC=<id>` | The page and script paths, and which steps were added, reworded or removed since each layer's last green run. |
| `/usecase run <id> [layer]` | `make usecase-run UC=<id> LAYER=<layer>` | Each step as passed, FAILED or not run, then the path of the full output. Needs `make db-up`. |

After `add`, open the page and fill it in, in this order:

1. The story: who is the person, what do they want, what do they see.
2. The people table, and the line "In this example we will do X. It assumes Y and Z."
3. The Stories table, then the numbered steps with what each one expects.
4. The script for each layer, one check per step, named by its number: `check("3 the module is published", ...)`.

Scripts start services with `docs/usecases/lib/usecase_harness.py` (api, sdk, cli) and read the SDK in `sdk/python`;
`packages/usecase-runner` runs them and reads the PASS and FAIL lines. Use what is there before writing anything new.
Then run the new use case once with `/usecase run`; the stub fails until its steps are written.

## Reading a run

- `passed` is a step whose check passed. `FAILED` shows the check name and its detail. `not run` means the script
  stopped before that step. `open` marks a step the product cannot do yet.
- A failure's full output is in `.run/usecases/<id>-<layer>.log`. Read it before guessing at a cause.
- A story works only when its proving step passed and none of its steps failed.

## Rules

1. Steps run only through the public SDK, the CLI or the console. A step that cannot is a product gap: keep it in
   the table as **Open**, file a card for it, and never add a helper, a database write or a private route to get past it.
2. No new console (ui) tests for now. `add` refuses the ui layer; existing ui scripts still run.
3. Scripted model only: the runner removes model keys, and a real model call needs an approved count in
   `APPROVED_REAL_CALLS=<n>`.
4. Watch a new check fail once: break the behaviour, see the story go broken at the right step, restore it.
5. The registry's status column is not evidence; only a run in this session is.
6. Never kill a process you did not start. A run picks free ports itself, so a busy port is not yours to free.

## Proof

```bash proof
make usecase-list AREA=tools
make usecase-update UC=uc-007
make usecase-run UC=uc-007 LAYER=api
```
