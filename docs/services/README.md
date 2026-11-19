# Services

Status: current, checked against the code on 2026-11-18. Eight services are built; each page below says which of its parts are partial or not built.

Ops AI runs as eight backend services. Each one owns its own tables, verifies every caller itself and reaches another
service only through that service's API or an event. This page lists them, the shape every service page follows, and
the commands that work the same way in each service folder.

## The services

<!-- site: cards -->
| Service | What it owns |
|---|---|
| [Platform service](platform-service/overview.md) | Sign-in, sessions, teams, members, roles, API keys, policies and the audit log; the only service that issues identity tokens |
| [Agents service](agents-service/overview.md) | Agents, workflows and their versions, chat, threads and runs, Human Tasks, cases, channels and triggers |
| [Tools service](tools-service/overview.md) | The one way out for tool calls: tool modules, app accounts, secrets, the egress allow-list, approvals and the call log |
| [Models service](models-service/overview.md) | The one way out for model calls: aliases, provider connections and keys, model keys with budgets, and a call log without prompt text |
| [Knowledge service](kb-service/overview.md) | Knowledge bases, their sources, sync, the search index and citations |
| [Files service](files-service/overview.md) | File bytes and metadata: uploads, downloads, scanning, dedupe, retention, legal holds and storage settings |
| [Documents service](documents-service/overview.md) | What is read from a file: readings, extractions with page positions, document types, samples and corrections |
| [Runner service](runner-service/overview.md) | Runs a code tool's Python in a WASM sandbox with no network, no secrets and no database |

There is no human-in-the-loop service: `services/hitl-service` holds only a README and a stub Makefile, and Reviews,
Cases and work items are served by agents-service until the planned `ops_hitl` package takes them.

![Callers reach agents-service; every tool and model call leaves through tools-service and models-service; files and documents are separate services](../diagrams/component-map.svg)

Who calls whom and why, the events between services and where each can be deployed are in the
[service map](../architecture/service-map.md). Every table, by the service and store module that owns it, is in the
[data model](../architecture/data-model.md) and the generated inventory in [data](../architecture/data.md#inventory).

## What every service page holds

Each service's `overview.md` uses the same sections in the same order, so a reader finds the same fact in the same
place on every page.

| Section | Answers |
|---|---|
| At a glance | What it owns, its port, its tables, how tenants and teams are kept apart, the secrets it holds, what it calls and who calls it, the events it sends and receives, what happens when a dependency is down |
| How a call flows | A small diagram of the service's main path |
| Run and test it alone | The make targets for this service, checked against its `Makefile` |
| Routes | A pointer to the API reference tab, which is built from the service's committed `openapi.json`; the page itself only explains behaviour the reference cannot show |
| Detail sections | The rules the code enforces, with `file:line` references |
| Not built yet | What is designed and missing, so nobody reads it as working |
| Gotchas | What has cost someone time before |

## Commands that work in every service

| Task | Command |
|---|---|
| Start the whole stack (every service, the agents worker, the console and the dev fakes) | `make up`, then `make health` |
| Serve one service in the foreground | `make -C services/<name>-service run` |
| Restart one service the stack started, migrating it first | `make restart SVC=<name>` (`platform`, `agents`, `worker`, `tools`, `models`, `kb`, `files`, `documents`, `runner`) |
| Follow one service's log | `make logs SVC=<name>` |
| Apply one service's migrations | `make -C services/<name>-service migrate`; `make migrate` applies every chain |
| One service's tests on a throwaway database | `make test PKG=services/<name>-service` (`T=` names files) |
| Lint, strict types, tests and the OpenAPI drift gate | `make -C services/<name>-service verify` |
| Regenerate the committed OpenAPI document | `make -C services/<name>-service openapi` |
| One use case end to end | `make usecase-test UC=<id>` |

Two exceptions: runner-service has no database, so no `migrate`, and platform-service has no `openapi` target; it
regenerates its document with `uv run python scripts/check_openapi.py --write` in `services/platform-service`.

> [!NOTE]
> **Databases.** Every service runs on PostgreSQL today. SQL Server 2025 support is partial: CI's `store-mssql` job
> (`.github/workflows/ci.yml:217`) runs the store, service-kit and identity suites and each service's store and
> isolation tests on SQL Server 2025, and a full install on it is not yet proven ([Azure SQL](../guide/azure-sql.md)).
