# Contributing

Status: current.

Start here if you are changing Ops AI itself. This page says how the repository is laid out, where the rules and
designs live, and how to check a change. Setting up, branching, commit messages and pull requests are in the
[contributing guide](../../CONTRIBUTING.md) at the root of the repository.

## How the repository is laid out

| Folder | What it holds |
|---|---|
| `services/` | The backend: one Python service per job (platform, agents, tools, knowledge base, models, runner, documents, files) |
| `packages/` | Libraries the services share: the data layer, access rules, sign-in, the use-case runner |
| `apps/` | The console, the embeddable chat and this documentation site |
| `sdk/` | The Python and TypeScript clients and the command line, generated from each service's API document |
| `plugins/`, `builtin-plugins/` | The connectors and templates that ship with the product, and the plugin kit they build on |
| `deploy/`, `make/`, `scripts/` | Release and database scripts, the make targets, and the checks |
| `docs/` | Every page on this site |

## Where things live

| You want | Go to |
|---|---|
| How the system fits together and why | [Architecture](../architecture/README.md) |
| The rules a change is reviewed against, each with the check that enforces it | [Engineering standards](../architecture/engineering-standards.md) |
| What one service does, its routes, tables and tests | [Services](../services/README.md) |
| What one shared library does | [Packages](../packages/README.md) |
| The end-to-end checks that prove a feature | [Use-case catalogue](../usecases/README.md) |
| Designs proposed or approved | [Design proposals](../design/README.md) |
| The skills a coding assistant uses in this repository | [Agent skills](../guide/skills/ops-run.md) |
| How a release is cut and shipped | [Release process](../deploy/release.md) |

## Run the checks

| Command | What it runs |
|---|---|
| `make verify` | Everything a commit must pass: console, docs, Python and SDK checks. Run it before each commit |
| `make test` | The tests for what changed since the main branch; `make test PKG=services/<name>` runs one |
| `make usecase-test UC=<id>` | One use case end to end, optionally one layer with `LAYER=api`, `sdk`, `cli` or `ui` (needs `make db-up`) |
| `make help` | Every target |

A change to a screen, an API or a data model is done when its use case has run, not when its unit tests pass.

## Next

<!-- site: cards -->
- **[Contributing guide](../../CONTRIBUTING.md)**: Set up, branch, commit and open a pull request.
- **[All documents](../README.md)**: Every page in the repository's docs, with one line on each.
