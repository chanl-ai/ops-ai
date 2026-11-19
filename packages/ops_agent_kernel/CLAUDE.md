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
| `skills` | The skill index, always-on bodies and the `load_skill` built-in, with per-turn caps; loading a skill replaces the one carried from an earlier reply |
| `steps` | Skills that run step by step: the program a skill version stores (models in `ops_contracts.skill_run`), the problems that stop one from running, and the running-skill record's moves (start, pass, fail, exit, sub-skill) |
| `expr` | A step's rule check: a whitelist walk over `ast.parse`, reading `result` and `inputs`; nothing is compiled or executed |
| `step_tools` | The built-ins `switch_skill`, `step_done` and `exit`, counted apart from the cap on kernel tools |
| `prompt_writer` | `Brief`, `Patterns`, `head(name, brief)` (the agent's stable instructions) and `tail`, written before every model request: the current step, the skill's rules, the never rules last |
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
- The running-skill record is returned on `TurnResult.run` whichever way a turn ends, and on `Interrupt.run` at a pause;
  the caller hands it back as `TurnRequest.carried_run`. A rule check runs once on the tool result as it arrives; the
  returned record is masked with the rest of the result, the one on an interrupt is not.
- While a skill's step names a tool, that tool and knowledge search are the only systems offered; tools other steps
  name wait for their step, and a failed skill's tools stay withheld until it starts again, in every later reply of
  the thread and also when another skill's current step names one. A step that runs a skill hands it the inputs it
  declares, from the running skill's inputs and then the result of the step before; a required one missing fails
  the step.

Depends on `ops_service_kit`, `ops_contracts` and `ops_pii`. Depended on by `ops_engine`, agents-service and tools-service.

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

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [layers and ownership](../../docs/architecture/standards/layers.md) (`LY1` to `LY9`), [security](../../docs/architecture/standards/security.md) (`SC1` to `SC6`), [errors, logging and observability](../../docs/architecture/standards/observability.md) (`OB1` to `OB6`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
