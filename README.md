<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://opsai.chanl.ai/docs/media/logo-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="https://opsai.chanl.ai/docs/media/logo-light.svg" />
    <img src="https://opsai.chanl.ai/docs/media/logo-light.svg" alt="Ops AI" width="80" />
  </picture>
</p>

<h1 align="center">Ops AI</h1>

<p align="center">
  <b>An open-source agent and workflow platform for regulated operations teams.</b><br />
  Put agents and workflows to work on your team's operations, with a person approving every change that matters and
  a record of every run that a risk review can read.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0" /></a>
  <a href="https://github.com/chanl-ai/ops-ai/actions/workflows/ci.yml"><img src="https://github.com/chanl-ai/ops-ai/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
</p>

<p align="center">
  <a href="#you-have-a-queue-ai-could-clear">Why</a> &bull;
  <a href="#a-card-dispute-from-request-to-record">See it work</a> &bull;
  <a href="#quick-start">Quick start</a> &bull;
  <a href="#three-things-to-try">Try it</a> &bull;
  <a href="https://opsai.chanl.ai/docs">Docs</a>
</p>

## What Ops AI is

Ops AI lets you build agents and workflows for the operations work in a bank, an insurer or any other regulated
business. Every tool, data and model call goes through a gateway, a person approves the steps that change data, and
every run keeps a record of who approved what, which version ran and what it could reach. It runs on your own
machines, and the whole stack starts without a model key.

## You have a queue AI could clear

You run an operations team, or you build tools for one. A card team works through hundreds of disputes a week. A
claims team reads the same policy wording fifty times a day. A model can already draft most of this work.

The pilot usually goes well. Then the risk review asks three questions: who approved the change to the customer's
account, which version of the agent ran, and what data it could reach. Most agent tools can't answer them, so the
team either stops at the pilot or builds approvals, versions and an audit trail by hand for every new use case. While
that happens, your team keeps working the queue by hand.

Ops AI builds those answers into every run:

| A reviewer asks | What Ops AI records |
|---|---|
| Who approved this change? | The workflow waits on a human task. The person decides with the facts in front of them, and the call that runs is bound to exactly what they approved |
| Which version ran? | Agents and workflows are published as fixed versions, and each run keeps the version it started on |
| What could it reach? | Every tool and data call goes through one gateway and every model call through another, with access set per team and a log of every call |

## How you get there

1. **Install it on one machine.** Two `make` commands install and start every service, the console and a built-in test model,
   so you can try it before you have a model key.
2. **Build an agent and a workflow.** Write the agent's instructions, give it tools for your systems and a knowledge
   base to answer from, and place it in a workflow next to fixed steps that run the same way every time.
3. **Put a person on the steps that matter.** Any step that changes data waits for someone to approve it, and the
   run keeps the record.

## A card dispute, from request to record

The sample team that the quick start installs includes a card dispute workflow. It shows how fixed steps, an agent
and a person share one piece of work. The bank, its people and its customers are fictional.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="https://opsai.chanl.ai/docs/media/workflow-dark.png"><img src="https://opsai.chanl.ai/docs/media/workflow-light.png" alt="The Card dispute intake workflow on the canvas: Dispute received, Find the cardholder, Is it them?, Their accounts, Check the dispute, Open the dispute case and Approve the provisional credit, with the failure ends below" width="900"></picture></p>

1. **The dispute comes in.** A cardholder's dispute arrives as a request with the cardholder's name, the merchant,
   the amount, the date it posted and what went wrong. The workflow starts on its own.
2. **Fixed steps find the cardholder.** The workflow searches the core banking system for the customer, checks that
   the match is the right person and reads their accounts. These calls go through the tool gateway and run the same
   way every time. When the lookup fails or the cardholder can't be confirmed, the run ends at its own failure step
   instead of guessing.
3. **An agent checks the dispute against the handbook.** Dispute Desk reads the card dispute handbook and answers in
   a fixed shape: the reason category, whether provisional credit is due, whether a team lead must approve it, and a
   short summary for the analyst. The workflow checks that shape before it moves on.
4. **A case opens and a person decides.** The workflow opens a case for the dispute, then waits on a human task
   titled with the amount and the cardholder. The reviewer sees the dispute, the agent's assessment and the accounts
   before approving or declining, and the task shows as overdue if nobody decides within 24 hours.
5. **The record stays behind.** An approval is noted on the case with the reviewer's name, and the run ends at
   Credited. A decline ends at Declined. Either way the run keeps its full path and the version it ran on.

[Card disputes](docs/guide/use-cases/card-disputes.md) walks through the same workflow in the console.

## What you can do with it

| You get | What it does | Status |
|---|---|---|
| Governed agents | Instructions, a model alias, tools and knowledge; every save is a version and publishing goes through review | Built |
| Workflows | A visual editor over 25 step types: fixed steps, AI steps, human tasks, tool calls and cases; a run keeps its version | Built |
| Tools with approvals | OpenAPI documents and MCP servers imported as tools; an approval is bound to the exact input; every call is logged | Built |
| Knowledge | Knowledge bases searched by meaning and keyword, with answers cited by page and section | Built |
| Evals | Test cases saved on an agent, with every run kept. The pass rate is reported on each publish request | Partial: the pass rate does not stop a publish yet |
| Console, SDKs and CLI | A Next.js console, Python and TypeScript SDKs and the `opsai` command on one public API | Built; the SDKs install from this repository |
| Databases | PostgreSQL 15 or newer. SQL Server scripts are ready for a DBA's review ([Azure SQL](docs/guide/azure-sql.md)) | PostgreSQL Built; SQL Server Partial: the services do not run on it yet |

[What's built today](docs/guide/whats-built-today.md) gives the status of each capability in more detail.

## Quick start

The quick start runs every service, the console and a built-in fake model on your machine. You need these tools:

| Tool | Used for |
|---|---|
| [uv](https://docs.astral.sh/uv/) | The services and the `opsai` command, on Python 3.12, which uv downloads when it is missing |
| Node 22 or newer and pnpm 10 (`npm install -g pnpm@10`) | The console |
| Docker with Compose, running | PostgreSQL, OPA and two test mail servers |
| Optional: [Tesseract](https://tesseract-ocr.github.io/) | Reading scanned files; without it `make health` shows documents as `degraded` |

You don't need a model key. With no `OPENAI_API_KEY` set, every model alias answers from the fake model. One stack
runs per machine, on ports 3016, 3017, 3020, 8700 to 8770, 8799, 8181, 5477, 3025, 3143, 1025 and 8025.

```bash
git clone https://github.com/chanl-ai/ops-ai.git && cd ops-ai
make install        # pnpm install and uv sync, once per clone
make up             # database, migrations, every service, the console, and a sample team on a new database
make health         # each service with its port and state
```

Open <http://localhost:3016> and sign in as `w.kamau@harborpine.example` with the development password
`northfield-demo`. The bank, its people and its customers are fictional sample data.

The console at <http://localhost:3016> does not serve the API. Each service serves its own part of the API on its own
port: platform 8710, agents 8700, tools 8720, kb 8740, files 8750 and documents 8760. One reference page for all of
them is at <http://localhost:8799>. The SDKs and the CLI take those addresses as `services`. A deployed install puts
them behind one address, which is the SDK's `base_url`.

To stop the stack and keep your data, run `make down KEEP_DB=1`. To answer with a real model, put `OPENAI_API_KEY` in
a `.env` file at the root and run `make up` again. Git ignores that file, and [`.env.example`](.env.example) lists
the other settings.

## Three things to try

Each of these runs against the stack from the quick start.

**1. Chat with an agent.** The answer streams to your terminal, with a link to the same conversation in the console.
On the fake model, the reply repeats what the agent retrieved, so you can see the knowledge search and its citations.

```bash
make chat-agents AS=builder
make chat AS=builder AGENT='Branch Policy' SAY='What is the daily cash withdrawal limit at a branch?'
```

**2. Build and run a workflow from a folder.** `setup.py` signs you in and writes a local profile into the folder.
The `opsai` command then validates the workflow file, saves it and starts a test run.

```bash
uv run python examples/workflows/01-normalize-a-request/setup.py
cd examples/workflows/01-normalize-a-request
OPS_CONFIG=.ops-profile.json uv run opsai workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json uv run opsai workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json uv run opsai workflows run normalize_support_request --input fixtures/valid.json --test --wait
cd ../../..
```

**3. Call the API from Python.** The profile from step 2 holds the service addresses, the team and a sign-in, so the
client needs no arguments. If the sign-in has expired, run `setup.py` again. In your own install, you pass
`base_url`, `api_key` and `team` instead ([Python SDK](docs/sdk/python.md), [TypeScript SDK](docs/sdk/typescript.md)).

```bash
OPS_CONFIG=$PWD/examples/workflows/01-normalize-a-request/.ops-profile.json uv run python -c "
from ops_ai import OpsAI
ops = OpsAI()
run = ops.workflows.run('normalize_support_request', mode='test', wait=True,
    input={'customerEmail': 'ada@example.test', 'subject': 'Card', 'message': 'Where is my refund?'})
print(run['status'], run.get('outcome'))
"
```

It prints `succeeded accepted`. The next examples add a model step, a tool call and a person's approval.
[`examples/`](examples/README.md) has one folder per idea, and
[`04-draft-and-approve-a-reply`](examples/workflows/04-draft-and-approve-a-reply/README.md) holds a reply until a
person approves it.

## Documentation

The full documentation is at <https://opsai.chanl.ai/docs>. These pages are good places to start:

| Read | For |
|---|---|
| [Build with Ops AI](docs/guide/build-with-ops-ai.md) | The developer path, then the [agents](docs/guide/agents.md) and [workflows](docs/guide/workflows.md) manuals |
| [Security and governance](docs/guide/security-and-governance.md) | Approvals, roles, sign-in and audit |
| [Install](docs/guide/install.md) | Running it on a server: the install script, Docker Compose, Kubernetes |
| [Architecture](docs/architecture/README.md) | How the services, the gateways and the runtime fit together |
| [docs/README.md](docs/README.md) | The map of every document |

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) covers the standards, the checks a change must pass (`make verify`) and how to
write commit messages. [`AGENTS.md`](AGENTS.md) holds the rules for coding agents. To report a vulnerability, follow
[`SECURITY.md`](SECURITY.md).

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
