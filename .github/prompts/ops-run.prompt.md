---
name: ops-run
description: Run the Ops AI stack locally, in the devcontainer or on a shared VM workspace, on the fake model or OpenAI. Use when someone asks to start, stop or set up Ops AI, or which make target runs it.
agent: agent
---

# ops-run: run Ops AI on a laptop, in the devcontainer or on the shared VM

<!-- Generated from `docs/guide/skills/ops-run.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make setup, make install, make up, make health, make down.

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

## Proof

```bash proof
SETUP_FILE=/tmp/ops-run.env make setup ANSWERS=scripts/setup/answers.qa.env
make up DEMO_MODEL=fake || make health
make health
```
