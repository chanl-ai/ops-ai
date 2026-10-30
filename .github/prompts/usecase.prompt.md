---
name: usecase
description: List, show, write, run and report end-to-end use cases (docs/usecases) as plain user stories at the api, sdk, cli or ui layer. Use when someone asks to prove a change end to end, run or add a use case, says which stories work, or types /usecase list|show|new|test|report.
agent: agent
---

# usecase: prove a change with the stories a person can do

<!-- Generated from `docs/guide/skills/usecase.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make usecase-list, make usecase-show, make usecase-new, make usecase-test, make usecase-report, make usecase-coverage.

## What a use case is

Four or five plain stories that work, such as "A team admin connects Salesforce and runs Test connection". Each story
has one layer (ui is the console in a browser, sdk is the Python or TypeScript SDK, cli is a command a person runs, api
is the HTTP routes), the steps it takes and the one step whose check proves it. A run reports each story as works or
broken, with the step that failed; the detailed checks stay underneath as the evidence. The registry and rules are in
`docs/usecases/README.md`.

## Verbs

| Verb | Run | Then |
|---|---|---|
| `list` | `make usecase-list` | The registry as printed |
| `show <id>` | `make usecase-show UC=<id>` | Open its doc; say its stories and which layers have scripts |
| `new <service> "<title>"` | `make usecase-new SERVICE=<service> TITLE="<title>"` | Write the Stories table first, then the steps that make them up, then the script |
| `test <id> [layer]` | `make usecase-test UC=<id> LAYER=<layer>` (needs `make db-up`) | Paste the Stories block and the summary line; a broken story is reported with its step, never explained away |
| `report [<id>]` | `make usecase-report UC=<id>` | The stories from each layer's latest run, without running anything; "not run" names the command to run |
| `coverage <service>` | `make usecase-coverage SERVICE=<service>` | Missing scripts per layer |

## Writing one

1. The doc's `## Stories` table has the columns `# | Story | Layer | Steps | Proved by`: `S1`, the story in a person's
   words (who, what they do, what they see), one layer, its rows of the steps table (`1-3, 5`), and the step that
   proves it. Four or five stories; a sixth means a second use case.
2. The script names each check by its step: `check("3 the module is published", ...)`. A check with no number, such
   as "no page errors", belongs to no story and is shown only when it fails.
3. Scripts live at `docs/usecases/<service>/scripts/test-<id>-<layer>.{py,mjs}`: api scripts start services with
   `docs/usecases/lib/usecase_harness.py`; ui scripts drive the console through `withUiStack` from
   `@ops-ai/usecase-runner/harness`; sdk scripts call `sdk/python`; cli scripts run the command as a person would.
4. Drive only what a client can drive; never reach into a database. Assert values (the id, the amount, the status),
   not that a field exists.

## Rules

1. Scripted model only: the runner removes model keys, and a real model call needs the owner's approved count in
   `APPROVED_REAL_CALLS=<n>`.
2. A story works only when its proving step passed and none of its steps failed. A script that stops early leaves the
   rest broken at the step that never ran.
3. Watch it fail once: break the behaviour (or point the script at a case that must fail), see the story go broken at
   the right step, restore it, and say what was broken.
4. The registry's status column is not evidence; only a run in this session is.
5. Never kill a process you did not start; a busy port means `ISOLATED=1` or stopping your own leftover.

## Proof

```bash proof
make usecase-list
make usecase-show UC=uc-531
make usecase-test UC=uc-531 LAYER=api
make usecase-report UC=uc-531
```
