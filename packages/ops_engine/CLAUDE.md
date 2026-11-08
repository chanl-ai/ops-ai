# ops_engine: working rules

Status: current.

The workflow runner's library: the node type registry, v2 workflow definitions and their checks, the compiler from a
definition to a LangGraph graph, the node wrapper with its step journal, the work queue and the worker loop. It
imports nothing from `ops_agents`. agents-service hosts it today and implements every port it reaches. Package rules
and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `node_types` | `TypeRegistry`, `NodeType`, `Port`, `Retry`, `BASIC_TYPES`, `default_registry`: what each kind of node is, read by the editor, the validator and the runner |
| `definition` | Schema version 2 definitions: node instances joined by port connections, and their checks |
| `compiler` | A definition becomes a LangGraph `StateGraph`; every node runs inside one wrapper with one state channel per node |
| `journal` | The step journal contract, one row per node attempt; `MemoryJournal` for the engine's own tests |
| `shapes` | Each step's output shape (JSON Schema) by the port it leaves by, known before the workflow runs |
| `ai_steps` | Classify, Summarise, Extract from text and Draft: one executor over one model call through `EnginePorts.prompts` |
| `document_types` | Pins a document type version into an Extract from file step when the workflow is saved |
| `starts` | `StartSpec`: how a person starts a workflow by hand, declared by its trigger type |
| `worker` | Claims work, takes the run's thread lease, runs the compiled graph and records how it ended |
| `ports` | `EnginePorts` and every port the engine reaches outside itself (tools, reviews, agents, documents, files, knowledge, timers, runs, cases, expressions, task types, prompts), plus `LeasePort` and `EventPort` for the worker |
| `store/` | The engine's tables, runs, step journal, work queue, definitions and the run reconciler, on SQLAlchemy Core |

## Contract with callers

- The host implements the ports in `src/ops_engine/ports.py`; moving the engine into its own service means moving
  this package and re-implementing the adapters, nothing else. `EnginePorts.tools` and `reviews` are required; the
  rest are `None` until a node type needs them.
- The engine never decides tenancy: `store/tx.py` asks the host for its row-level-security transactions, and the
  migrations for the engine's tables live in agents-service's chain, which forces RLS on `tenant_id`.
- Node types are data in the registry. A new step type is a `NodeType` with ports, a parameter schema, a `ui` form,
  an effects class and an executor; no use case gets its own code path (root rule "Use cases are configuration").
- Times the queue compares are the database's clock (`store/clock.py`).

Depended on by agents-service only. Depends on `ops_service_kit`, `ops_store`, `ops_agent_kernel` and
`ops_checkpointer`.

## Run and test

| Task | Command |
|---|---|
| The suite (in-memory journal and fakes; about 10 s) | `make test PKG=packages/ops_engine` |
| One file | `make test PKG=packages/ops_engine T=tests/test_compiler.py` |
| The engine's store on PostgreSQL | `make test PKG=services/agents-service T=tests/engine` (the tables come from agents-service's chain; about 2 minutes, 201 tests) |
| Lint, format, types | `uv run ruff check packages/ops_engine`, `uv run ruff format --check packages/ops_engine`, `uv run pyright packages/ops_engine` |

The package tests use `tests/fixtures/basic.yaml` and fakes for every port; they need no database or model. A change
here also runs agents-service's suite under `make test` with no `PKG`.

## Gotchas

| Gotcha | Rule |
|---|---|
| The work queue claims with `with_for_update(skip_locked=True)` (`src/ops_engine/store/work.py:56`), which renders nothing on SQL Server | The queue is PostgreSQL only today, as its docstring says; SQL Server support needs `ops_store.dialect.claim` |
| Definitions with `schemaVersion: 1` belong to agents-service's v1 compiler (`src/ops_engine/definition.py:15`) | This package reads only version 2 |
| A step's AI call goes through `EnginePorts.prompts`, never a provider client | Tests stay on fakes; real model calls follow the cap in the root guide's [tests](../../CLAUDE.md#tests) section |

## Reference docs

- [docs/architecture/workflow-runner.md](../../docs/architecture/workflow-runner.md): the runner's design and its ports
- [docs/design/workflows/workflow-nodes.md](../../docs/design/workflows/workflow-nodes.md): the node types
- [docs/guide/skills/ops-workflow-step.md](../../docs/guide/skills/ops-workflow-step.md): adding a workflow step type
- [docs/architecture/decisions/execution-engine-seam.md](../../docs/architecture/decisions/execution-engine-seam.md) and [workflow-definition-format.md](../../docs/architecture/decisions/workflow-definition-format.md)
