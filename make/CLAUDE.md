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
| One target per rule line for help | `HELP_AWK` (`env.mk:138`) matches `^[a-z0-9-]+:.*## `, so a rule that names two targets on one line is left out of `make help`. `chat-show chat-calls` and `chat-agents chat-accounts chat-kbs` (`dev.mk:131`, `dev.mk:134`) are missing from `make help` for this reason |
| No `AS ?=`-style defaults on make's built-in names | Make defines `AS` (`as`), `CC`, `LD` and others itself, so `?=` never applies: `AS ?= admin` (`dev.mk:115`) has no effect and `AS=` must be given |
| Tests never drive the stack | `env.mk` refuses `up`, `down`, `restart`, `migrate`, `reset-db` and the other stack goals when `PYTEST_CURRENT_TEST` is set |
| Update the doc in the same change | `docs/architecture/make.md` lists every fragment, target and variable |

Any change to a file here makes `make test` (with no `PKG`) run the full `make verify` (`scripts/verify-changed.sh`).
Check a change with `make help`, `make -n <target>` and the fragment's own test where there is one
(`uv run pytest -q scripts/tests/test_make_stack.py` for the stack targets).

## Calling the API as a person (`dev.mk`)

Each target signs a seeded person in through the real password sign-in (`POST /v1/auth/sign-in`) and calls the same
routes the console calls, with the same `Authorization` and `X-Team-Id` headers. Sessions are cached in
`.run/api-tokens/` (mode 600) until they expire; no password is printed. Code: `scripts/api_as.py`, `scripts/chat_as.py`.

| Target | Does | Example |
|---|---|---|
| `api` | One HTTP call; prints the status and the JSON body; exits 1 on a status of 400 or more | `make api GET /v1/me AS=viewer` |
| `sdk-call` | One Python SDK expression with `ops` bound to a signed-in client | `make sdk-call CALL='ops.raw.platform.me_me()' AS=builder` |
| `chat` | One chat turn as the chat screen sends it (new thread, or `THREAD=`), with the reply, its phases, tool calls, any Connect card and the call log printed | `make chat AS=james SAY='Reply with the single word ok.'` |
| `chat-script` | A scripted conversation from a JSON file, PASS or FAIL per turn | `make chat-script FILE=docs/usecases/chat/salesforce-case-helper.json AS=james` |
| `chat-show` | A thread as the chat reads it | `make chat-show THREAD=th_… AS=james` |
| `chat-calls` | A thread's tool-call log (tools-service `GET /v1/executions?thread=`) | `make chat-calls THREAD=th_… AS=james` |
| `chat-agents` | The agents New chat offers this person | `make chat-agents AS=james` |
| `chat-accounts` | My accounts: the app accounts this person connected | `make chat-accounts AS=james` |
| `chat-kbs` | The knowledge bases this person may attach | `make chat-kbs AS=james` |

| Variable | Meaning |
|---|---|
| `AS` (always give it) | A role from `services/platform-service/seed/dev-roles.json` (`admin`, `builder`, `approver`, `viewer`, `security`, `platform`), a seeded person's full name, first name or email name from `people.json` (`james`, `priya`, `maya`, `ravi`, `nadia`, `sam`, `wanjiru`), or an email |
| `TEAM` | The team to act in; default is the person's first team |
| `SVC` (`api` only) | The service to call. Default: the one service whose `openapi.json` holds the path. Name it when two hold the path (`/v1/chat/threads` needs `SVC=agents`) or none does (routes mounted with `include_in_schema=False`) |
| `Q`, `BODY` (`api` only) | The query string (`Q='pageSize=5'`; make reads any word holding `=` as a variable, so it cannot go in the path) and a JSON body |
| `AGENT`, `THREAD`, `TEST`, `KB`, `CONNECTED` (`chat`) | The agent by id, slug or name (default: the team's default agent); an existing thread; `TEST=1` picks from every agent, published or not, and marks the thread a test; a knowledge base to attach; `CONNECTED=<app>` sends the follow-up a Connect card sends once the person has signed in |
| `ENV=staging` (`api`, `sdk-call`) | Calls the staging app named by `STG_APP` instead of the local stack; only the staging admin's sign-in is kept on a machine, so only `AS=admin` works there ([docs/deploy/fly-staging.md](../docs/deploy/fly-staging.md)) |

A chat-script file is `{"agent", "test", "kb", "turns": [{"say": "…" | "connected": true, "expect": {…}}]}`, where
`expect` holds any of `tool` (a tool name called), `noTool`, `card` (true or false), `says` (texts the reply holds)
and `credential` (`team` or `person`). Scripts live in `docs/usecases/chat/`. `make chat` and `make chat-script` call
whatever model the stack's aliases point at (`make demo-model`), so each turn may be a real model call.

## Other fragments in daily use

| Fragment | Targets |
|---|---|
| `dev.mk` | `up`, `down`, `restart`, `health`, `logs`, `ports`, `sample-team`, `demo`, `demo-walk`, `demo-model`, `demo-salesforce*`, `runner-wasm`, `reset-db` |
| `python.mk` | `test`, `python-install`, `python-verify`, `sbom` |
| `git.mk` | `commit`, `commit-hunks`, `my-hunks`, `whats-mine`, `unstage`, `git-rules`, `review` ([Commits](../CLAUDE.md#commits)) |
| `usecase.mk` | `usecase-test`, `usecase-report`, `usecase-list`, `usecase-show`, `usecase-coverage`, `usecase-new`, `usecase-reset`, `usecase-runner-test` |
| `sdk.mk`, `docs.mk` | `openapi`, `sdk`, `sdk-verify`, `sdk-check`; `docs-verify` |
| `db.mk`, `db-scripts.mk` | `db-up`, `db-down`, `db-shell`, `db-sweep`, `migrate`, `migration`; the DBA scripts ([deploy/CLAUDE.md](../deploy/CLAUDE.md)) |
| `release.mk`, `staging.mk`, `deps.mk`, `setup.mk`, `experiments.mk` | Releases, staging, dependency locks and mirrors, machine setup, agents-service experiments |
| `services.mk` | The generated `<verb>-<svc>` pass-throughs, for example `test-tools` runs `make -C services/tools-service test` |
