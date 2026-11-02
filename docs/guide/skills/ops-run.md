# ops-run: run Ops AI on a laptop, in the devcontainer or on the shared VM

Status: current. Proven by `make skills-proof`.

skill: ops-run
description: Run the Ops AI stack locally, in the devcontainer or on a shared VM workspace, on the fake model or OpenAI. Use when someone asks to start, stop or set up Ops AI, or which make target runs it.
targets: make setup, make install, make up, make health, make down, make api, make sdk-call

## When to use it

A developer wants the stack running: a first run on a fresh clone, a restart after pulling, or a switch between the
fake model and OpenAI.

## Steps

1. `make setup` asks where it runs, whether Docker is there, the database, any package mirror and the model provider,
   tests each answer live and writes only what passed (`.env` on a laptop, `.devcontainer/.env.local` in the
   devcontainer or a shared VM workspace). `make setup ANSWERS=scripts/setup/answers.qa.env` answers with our database
   container, no mirror and the fake model. `SETUP_FILE=<path>` writes somewhere else; never overwrite a person's own
   `.env` without asking them.
2. `make install` once per clone (pnpm and uv).
3. `make up DEMO_MODEL=fake` starts PostgreSQL, OPA, the mail fakes, every service, the worker and the console, makes
   the first admin (its password in `.run/dev-admin.env`) and prints a health table. `DEMO_MODEL=<model id>` reads
   documents and checks guardrails on OpenAI with `OPENAI_API_KEY`; real model calls cost money, so keep the fake for
   tests.
4. `make health` shows each service, its port and who started it; the console is at <http://localhost:3016>.
5. `make down` stops it (`KEEP_DB=1` keeps the database).

Inside the devcontainer (`OPS_INFRA=external`) the database and mail servers are side containers; the same targets
apply. `ISOLATED=1` on any target runs a second stack on ports +1000 with its own database.

## Call an API as a dev user

`make api GET /v1/me AS=viewer` calls any route as one of the standard dev users, the way the API's
`make api-get ENDPOINT=…` does. Each role is a seeded person (`services/platform-service/seed/dev-roles.json`), acting
in their first team (`TEAM=` overrides):

| `AS=` | Person | Team |
|---|---|---|
| `admin` (default) | Priya Shah | Operations, admin |
| `builder` | James Richardson | Operations, builder |
| `approver` | Maya Okafor | Operations, approver |
| `viewer` | Ravi Menon | Operations, viewer |
| `security` | Sam Adeyemi | Security, admin |
| `platform` | Wanjiru Kamau | Platform, admin |

It signs in through the password sign-in (`POST /v1/auth/sign-in`, the dev demo password from Settings), never the dev
header, keeps the token in `.run/api-tokens/` until it expires, and finds the service from the path in the services'
OpenAPI documents (`SVC=` names one). `BODY='{…}'` sends a body, `Q='pageSize=5'` a query (make reads a word holding `=`
as a variable, so the query cannot sit in the path). It prints the status and the answer and exits 1 on a refusal.
`make sdk-call CALL='ops.raw.tools.connections_list_systems()' AS=builder` makes one Python SDK call the same way.
`ENV=staging` signs in as the staging admin from `~/.config/ops-ai/staging-admin.env` (staging has that one person, so
only `AS=admin`). Use cases get the same people from `as_role(api, "viewer")` (`docs/usecases/lib/usecase_harness.py`)
and `asRole('viewer')` (`@ops-ai/usecase-runner/harness`).

A `make up` stack seeds everyone as an admin (`OPS_SEED_EVERYONE_ADMIN`, on by default in dev), so a viewer is refused
nothing there; set `OPS_SEED_EVERYONE_ADMIN=false` before `make up`, or prove a refusal in a use case, whose stack seeds
the roles as written (uc-614).

## Proof

```bash proof
SETUP_FILE=/tmp/ops-run.env make setup ANSWERS=scripts/setup/answers.qa.env
make up DEMO_MODEL=fake || make health
make health
make api GET /v1/me AS=viewer
```
