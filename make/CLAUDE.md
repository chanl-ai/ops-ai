# Make fragments: working rules

Status: current.

The root `Makefile` only includes these fragments, one per concern, and every service Makefile includes `env.mk`
through `service-common.mk` or `service-stub.mk`. Which fragment owns which target, every variable they read and the
one-stack gotchas: [docs/architecture/make.md](../docs/architecture/make.md). `make help` from the root lists every
public target with its `## ` comment. Rules shared with every folder:
[Working in one folder](../CLAUDE.md#working-in-one-folder).

## Changing a fragment

| Rule | Detail |
|---|---|
| One fragment per target | A target is defined in exactly one fragment; others call it (`up` calls `migrate` from `db.mk`) |
| Every public target is documented | A `## ` comment after the target, under a `##@` group; `make help` prints it |
| One target per rule line for help | `HELP_AWK` (`env.mk:138`) matches `^[a-z0-9-]+:.*## `, so a rule that names two targets on one line is left out of `make help`; give each target its own rule and `## ` text |
| No `?=` defaults on make's built-in names | Make defines `AS` (`as`), `CC`, `LD` and others itself, so `?=` never applies. `dev.mk` sets `AS := admin` only when `$(origin AS)` is `default` or `undefined` |
| Tests never drive the stack | `env.mk` refuses `up`, `down`, `restart`, `migrate`, `reset-db` and the other stack goals when `PYTEST_CURRENT_TEST` is set |
| Update the doc in the same change | `docs/architecture/make.md` lists every fragment, target and variable |

Any change to a file here makes `make test` (with no `PKG`) run the full `make verify` (`scripts/verify-changed.sh`).
Check a change with `make help`, `make -n <target>` and the fragment's own test where there is one
(`uv run pytest -q scripts/tests/test_make_stack.py` for the stack targets).

## Calling the API as a person (`dev.mk`, `cli.mk`)

Test and call the system through these targets, with `AS=` to act as a person, instead of ad-hoc scripts or SQL; read
the database only to diagnose. Each target signs a seeded person in through the real password sign-in
(`POST /v1/auth/sign-in`) and calls the routes the console calls, with the same `Authorization` and `X-Team-Id`
headers. `api` and `sdk-call` run `scripts/api_as.py`; every other target runs the `ops` command (`sdk/python`,
`src/ops_ai/_cli/`). Both keep sessions in `.run/api-tokens/` (mode 600) until they expire, one per person, and print
no password. `make help` prints each target's arguments.

| Area | Targets | Example |
|---|---|---|
| Any route | `api`, `sdk-call` | `make api GET /v1/me AS=viewer`; `make sdk-call CALL='ops.raw.platform.me_me()' AS=builder` |
| Chat | `chat`, `chat-script`, `assistant-evals` (REAL=1: the real subset, at most MAX_CALLS model calls), `chat-show`, `chat-calls`, `chat-agents`, `chat-threads`, `chat-accounts`, `chat-kbs`, `chat-connected`, `chat-approve`, `chat-reject`, `chat-submit` | `make chat AS=james AGENT='Ops Assistant' SAY='What cases are open?'` |
| Knowledge | `kb-bases`, `kb-show`, `kb-documents`, `kb-sources`, `kb-source`, `kb-items`, `kb-add-file`, `kb-add-text`, `kb-sync`, `kb-search`, `kb-changes`, `kb-change` | `make kb-search KB=kb_retail_products TEXT='overdraft fee' AS=james` |
| Apps and connections | `apps-list`, `apps-show`, `apps-add-tool`, `apps-accounts`, `apps-mine`, `apps-connect` (prints the sign-in link), `apps-test`, `apps-auth-configs` | `make apps-connect APP=plugin:opsai.salesforce AS=james` |
| Tools | `tools-list`, `tools-show`, `tools-run` (Mock unless `REAL=1`), `tools-calls`, `tools-call` | `make tools-run APP=plugin:acme.ticketdesk TOOL=ticketdesk_get_ticket INPUT='{"number": 1}' AS=builder` |
| Runs and Human Tasks | `runs-list`, `runs-start` (a test run unless `LIVE=1`), `runs-show`, `runs-events`, `runs-cancel`, `runs-retry`, `tasks-list`, `tasks-show`, `tasks-decide` | `make tasks-decide TASK=wfrun_…:task:1 DECISION=approve AS=approver` |
| Cases, files, documents | `cases-list`, `cases-show`, `cases-note`, `files-list`, `files-show`, `files-upload`, `documents-types`, `documents-type`, `documents-extractions` | `make files-upload FILE=notice.pdf PURPOSE=case_attachment AS=james` |
| People and models | `people-list`, `people-invite` (prints the invite unless `SEND=1`), `people-roles`, `people-me`, `models-aliases`, `models-providers`, `models-keys`, `models-test` (one paid test turn, only with `CONFIRM=1`) | `make people-invite EMAILS=a@bank.example ROLE=viewer AS=admin` |
| Memories | `memories-list`, `memories-forget`, `memories-forget-agent`, `memories-export` | `make memories-forget-agent AGENT='Ops Assistant' AS=james` |
| Test data | `test-data-clean` | `make test-data-clean SINCE=2026-11-07`, then the same with `CONFIRM=1` |

| Variable | Meaning |
|---|---|
| `AS` | A role from `services/platform-service/seed/dev-roles.json` (`admin`, `builder`, `approver`, `viewer`, `security`, `platform`), a seeded person's full name, first name or email name from `people.json` (`james`, `priya`, `maya`, `ravi`, `nadia`, `sam`, `wanjiru`), or an email. Default `admin` |
| `TEAM`, `JSON` | The team to act in (default: the person's own team); `JSON=1` prints the answer as JSON (`ops` targets) |
| `SVC`, `Q`, `BODY` (`api` only) | The service (default: the one whose `openapi.json` holds the path; name it for `/v1/chat/*`, which no document holds), the query string (`Q='pageSize=5'`, since make reads any word holding `=` as a variable) and a JSON body |
| `AGENT`, `THREAD`, `TEST`, `KB`, `CONNECTED` (`chat`) | The agent by id, slug or name (default: the team's default agent); an existing thread; `TEST=1` uses the agent page's Test panel, whose thread nothing remembers and the chat list leaves out; a knowledge base; `CONNECTED=<app>` sends the follow-up a Connect card sends once the person has signed in |
| `ENV=staging` (`api`, `sdk-call`) | Calls the staging app named by `STG_APP`; only the staging admin's sign-in is kept on a machine, so only `AS=admin` works there ([docs/deploy/fly-staging.md](../docs/deploy/fly-staging.md)) |

A chat script is YAML or JSON: `agent`, `test`, `kb` and `turns`, each turn `say: …` or `connected: true` with an
`expect` holding any of `tool` (a tool name called), `noTool`, `card` (true or false), `says` (texts the reply holds)
and `credential` (`team` or `person`). Scripts live in `docs/usecases/chat/` as `.yaml`, the one data format
`check-docs.mjs` accepts there. Each chat turn reaches whatever model the stack's aliases point at
(`make demo-model`), so it may be a real model call; a chat that tests a check belongs on a test thread (`TEST=1`), or
the person's memory learns the check as a preference.

### Test data

A dev seed sign-in (`AS=`, `ops --as`) is a test run, and what it makes carries the prefix `[test] ` in a field the
routes already store: a chat's title, an uploaded file's name, a knowledge page's title (`OPS_TEST_DATA=1` marks a
profile's runs the same way). `make test-data-clean` lists the marked conversations and files of every seeded person,
or of `AS=` alone, grouped by kind, and removes nothing until `CONFIRM=1`; then it deletes each through the console's
own delete route, signed in as its owner. It never touches anything unmarked or owned by someone else. Case notes,
run records and knowledge pages have no delete route, so they stay. Code: `sdk/python/src/ops_ai/_cli/testdata.py`.

## Other fragments in daily use

| Fragment | Targets |
|---|---|
| `dev.mk` | `up`, `down`, `restart`, `health`, `logs`, `ports`, `sample-team`, `sample-teams` (the first teams: Wealth, Lending, Risk), `demo`, `demo-walk`, `demo-model`, `demo-salesforce*`, `runner-wasm`, `reset-db` |
| `python.mk` | `test`, `python-install`, `python-verify`, `sbom` |
| `git.mk` | `commit`, `commit-hunks`, `my-hunks`, `whats-mine`, `unstage`, `git-rules`, `review` ([Commits](../CLAUDE.md#commits)) |
| `usecase.mk` | `usecase-test`, `usecase-report`, `usecase-list`, `usecase-show`, `usecase-coverage`, `usecase-new`, `usecase-reset`, `usecase-runner-test` |
| `sdk.mk`, `docs.mk` | `openapi`, `sdk`, `sdk-verify`, `sdk-check`; `docs-verify` |
| `db.mk`, `db-scripts.mk` | `db-up`, `db-down`, `db-shell`, `db-sweep`, `migrate`, `migration`; the DBA scripts ([deploy/CLAUDE.md](../deploy/CLAUDE.md)) |
| `release.mk`, `staging.mk`, `deps.mk`, `setup.mk`, `experiments.mk` | Releases, staging, dependency locks and mirrors, machine setup, agents-service experiments |
| `services.mk` | The generated `<verb>-<svc>` pass-throughs, for example `test-tools` runs `make -C services/tools-service test` |
