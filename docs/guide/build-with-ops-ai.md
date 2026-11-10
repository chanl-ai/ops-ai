# Build with Ops AI

Status: current.

A developer starts with one message, one search, and one read. Agents and workflows come next. The two public bridges come after those. Approvals, roles and evaluations come last.

## The ladder

| Level | What you do | Folder |
|---|---|---|
| Chat | Send one message and read the reply | `examples/chat/01-ask-once/` |
| Knowledge | Add one page and search it | `examples/knowledge/01-search-a-page/` |
| Tool | Call one read operation | `examples/tools/01-find-a-customer/` |
| Agent | Ask a published agent | `examples/agents/01-answer-from-instructions/` |
| Workflow | Validate and run three nodes | `examples/workflows/01-normalize-a-request/` |
| Workflow asks agent | An Agent step calls a published agent | `examples/compositions/01-workflow-asks-agent/` |
| Agent starts workflow | Chat calls a published workflow | `examples/compositions/02-agent-starts-workflow/` |

Full manuals: [workflows.md](workflows.md) and [agents.md](agents.md). Architecture and trust rules stay in [how-work-flows.md](how-work-flows.md).

## Two bridges

Agents and workflows stay separate systems. They meet only through public APIs.

A workflow Agent step names a published agent and maps the prompt. The workflow receives the agent's final answer.

An agent's published tool list may contain `workflow:<id>`. A call starts that workflow's live version on behalf of the signed-in person.

The first composition folders use the citing agent and the three-node workflow. Money movement and human review come later.

## One checkout

```bash
make install
make up DEMO_MODEL=fake
make sample-team
```

Then one folder-local command:

```bash
uv run python examples/workflows/01-normalize-a-request/setup.py
opsai workflows validate examples/workflows/01-normalize-a-request
opsai workflows test examples/workflows/01-normalize-a-request
```

## Artifact words

| Word | Meaning |
|---|---|
| Example | A teaching folder under `examples/` |
| Seed | Demo data a local stack starts with |
| Use case | Acceptance evidence under `docs/usecases/` |
| Guide | These pages |

Seeds are not the developer catalog. The generated [wf-builder seed page](skills/wf-builder/examples.md) is seed topology.

Example helpers and comments name the folder or the published id. They do not cite a card or a board slice. A public checkout has no board.

## Surfaces

Python, TypeScript and `opsai` expose the same lifecycle: validate, apply, publish, run in test mode, inspect, evaluate an agent. Replay, workflow evaluation and the Agent Run API stay **Planned** on [developer-surface-coverage.md](developer-surface-coverage.md).
