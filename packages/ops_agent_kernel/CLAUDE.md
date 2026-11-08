# ops_agent_kernel: working rules

Status: current.

One agent turn on Pydantic AI (spec 15, ADR-0014). The library drives model steps; the kernel owns everything that
crosses a boundary: context assembly, tool calls through the executor port with idempotency keys, a gated write ending
the turn as an `Interrupt` and resuming from one, guardrails, skills, tool search, chat widgets and personal-data
masking. It has no database and no Temporal. Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide
rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `kernel` | `run_turn(req, ports)`: an async stream of `KernelEvent`s for one turn; the agent object is built per turn and holds no state |
| `types` | `TurnRequest`, `TurnResult`, `AgentSettings`, `ToolGrant`, `Interrupt`, `Resume`, `ToolCallRecord`, `CitationRef`, `TokenUsage`, `Guardrail`, `Skill`, `WidgetTemplate` |
| `ports` | `ToolExecutor`, `ModelSource`, `KnowledgePort`, `ToolOutcome`: what the caller supplies; tests swap in fakes |
| `events` | The events a turn emits; the caller maps them to its stream protocol |
| `context` | Context in spec 15 section 3.1 order; untrusted content in labelled data blocks whose closing delimiter is escaped |
| `models`, `aliases` | `build_model(settings)` (direct provider key; an alias starting `claude-` selects Anthropic) or `ModelsServiceModels` by alias; a job's own alias (`guardrail-check`, memory extraction) falls back to the turn's model only on "no such alias" |
| `guard` | Blocked-topic guardrails: one structured classification before and after the answer; a failed check raises `GuardrailUnavailable` and the turn fails closed |
| `skills` | The skill index, always-on bodies and the `load_skill` built-in, with per-turn caps |
| `search` | `search_tools`: finds only tools the agent is granted |
| `present`, `kinds`, `layout` | The built-in `present` tool and the widget catalogue: every tree is rebuilt from closed field lists, so no HTML, script or link leaves the kernel |
| `pii` | Masks what a turn shows and returns; re-exports `ops_pii` |

## Contract with callers

- Trust facts (tenant, team, role, approval state) never enter model-visible text; they arrive on `TurnRequest` and the
  ports (`src/ops_agent_kernel/context.py:1`).
- Every tool call goes through `ToolExecutor` with an idempotency key; tools-service implements the other side and
  returns a `ToolOutcome` (`ops_tools.tools`, `knowledge_tools`, `code_runs`).
- A provider error fails the turn with a message that says so; there is no fallback chain between providers
  (`src/ops_agent_kernel/models.py:1`).
- The model sees real values so it can chain calls on an account id; only what is shown and returned is masked.

Depends on `ops_service_kit` and `ops_pii`. Depended on by `ops_engine`, agents-service and tools-service.

## Run and test

The kernel has no tests in this folder; they live in agents-service and run on a scripted model.

| Task | Command |
|---|---|
| The kernel's unit tests | `make test PKG=services/agents-service T="tests/unit/test_kernel.py tests/unit/test_pii_masking.py"` |
| Guardrails, skills, widgets, tool search | `make test PKG=services/agents-service T="tests/unit/test_guardrails_kernel.py tests/unit/test_skills_kernel.py tests/unit/test_widget_kinds.py tests/unit/test_tool_search_mode.py"` |
| Lint, format, types | `uv run ruff check packages/ops_agent_kernel`, `uv run ruff format --check packages/ops_agent_kernel`, `uv run pyright packages/ops_agent_kernel` |
| One real chat turn through the console's routes | `make chat AS=james SAY='…'` ([calling the API as a person](../../CLAUDE.md#calling-the-api-as-a-person)); it makes a real model call when the stack's alias is bound to one |

A change here runs agents-service's, tools-service's and `ops_engine`'s suites under `make test` with no `PKG`.

## Reference docs

- [docs/architecture/decisions/agent-loop-library.md](../../docs/architecture/decisions/agent-loop-library.md) (ADR-0014)
- [docs/architecture/agent-guardrails.md](../../docs/architecture/agent-guardrails.md)
- [docs/architecture/chat-widgets.md](../../docs/architecture/chat-widgets.md)
- [docs/architecture/runtime.md](../../docs/architecture/runtime.md)
