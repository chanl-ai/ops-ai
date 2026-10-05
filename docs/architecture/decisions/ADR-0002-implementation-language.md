# ADR-0002 Implementation language: Python, TypeScript, or both

Status: accepted (draft for review). Formerly DR-2.

## Context

The bank's existing agents are Python ([problem statement](../../background/problem-statement.md)).
Eval and ML tooling is mostly Python. The console mock is Next.js and TypeScript, and the platforms
the delivery team built before were NestJS and TypeScript. Temporal supports workflows in one language calling activities
in another on separate task queues, with JSON as the default payload encoding ([Temporal
blog][temporal-polyglot]).

## Options

| Option | Description |
|---|---|
| A. TypeScript everywhere | Control plane, interpreter and workers in TS; Python agents reached as remote services |
| B. Python backend, TypeScript UI | Interpreter, activities, agent host, eval harness and control-plane API in Python; Next.js UI and thin BFF in TS |
| C. TypeScript control plane, Python workers | API and interpreter in TS (our team's strength); agent and eval activities in Python |
| D. Java or Kotlin backend, Python agent workers, TypeScript UI | The bank-standard enterprise stack for the control plane and interpreter |

### Criteria and scores

| Criterion | Weight | A | B | C | D |
|---|---|---|---|---|---|
| Runs existing Python agents without a rewrite | 20 | 2 | 5 | 4 | 4 |
| ML, eval and agent-library ecosystem (LangGraph, LlamaIndex, eval frameworks) | 15 | 2 | 5 | 4 | 3 |
| Temporal SDK maturity for the interpreter | 15 | 5 | 4 | 5 | 5 |
| One implementation of definition validation (canvas check equals runtime check) | 15 | 4 | 5 | 2 | 2 |
| Type safety of definitions and API | 10 | 5 | 4 | 5 | 5 |
| UI stack (mock is Next.js) | 5 | 5 | 5 | 5 | 5 |
| Bank hiring and ownership after handover | 5 | 3 | 4 | 3 | 5 |
| Our team's speed in year one | 5 | 5 | 3 | 5 | 2 |
| Marginal effort per new workflow (new agent blocks and modules are written by bank teams in their language) | 10 | 3 | 5 | 4 | 3 |
| **Weighted total** | 100 | **3.50** | **4.60** | **4.00** | **3.70** |

Most new workflows need no code at all (see Throughput). Where they do, the code is a new agent
block or tool module, and the bank's agent authors write Python, which is why marginal effort
favours B.

Facts behind the scores: Temporal's OpenAI Agents SDK integration reached GA for Python in March
2026 and its LangGraph plugin is Python-only and in preview ([changelog][temporal-changelog],
[LangGraph plugin][temporal-lg], [OpenAI Agents][temporal-oai]). Worker Versioning is GA in every
SDK including Python v1.11+ and TypeScript v1.12+ ([versioning][temporal-wv]). Hiring claims are our
judgement and **unverified** for this bank.

## Decision

Option B. Python for the interpreter workflow, every activity, the agent-block host, the eval
harness and the control-plane API. TypeScript for the console and its BFF only.

**The boundary.** Two machine-readable contracts, both owned by the control plane:

| Contract | Format | Generated for TypeScript |
|---|---|---|
| Workflow definition | JSON Schema 2020-12, versioned by `schemaVersion` | Types for the canvas and forms; the UI validates for feedback, the server validates for truth |
| Control-plane API | OpenAPI 3.1 | Typed client behind the mock's `OpsApi`, `KnowledgeApi` and `CasesApi` interfaces, so the UI swaps `mock` for `http` without page changes |

Pydantic models are the source; JSON Schema and OpenAPI are generated from them in CI, and a CI
check fails if the generated TypeScript types differ from the committed ones. This is the
"one fact, one home" rule from [design lessons](../../specs/design-lessons.md).

## Consequences

### Strongest counter-argument and our answer

**"The delivery team builds in TypeScript and has written a Temporal flow runner in NestJS before.
Option C ships faster."** It would, by a few weeks. The cost is two implementations of the
definition validator and compiler: one in TS for the control plane and one wherever the Python-side
checks run, and such pairs drift ([design lessons](../../specs/design-lessons.md), "one fact in
several places"). The bank also owns the platform after handover, and its agent teams write Python.
We reuse that runner's design (a thin `defineFlow` wrapper so flow files never import Temporal) and
not its code.

### What would change this decision

- The bank's platform engineering standard is Java or Kotlin with a large team to own it: then D,
  with Python kept for agent and eval activities.
- Measured Python interpreter throughput under the Temporal Python sandbox falls short of the
  bank's peak intake (to be load-tested in the [implementation plan](../../plan/implementation-plan.md), phase 1).

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Python control-plane API and interpreter; Pydantic models as the source; generated JSON Schema, OpenAPI and TypeScript types; CI equality check | A second-language agent-block host (for example .NET) if the bank has agents outside Python |
| The mock's HTTP client wired to the generated client | Public SDK for bank teams writing modules |

## Sources

[temporal-changelog]: https://temporal.io/changelog
[temporal-lg]: https://docs.temporal.io/develop/python/integrations/langgraph
[temporal-oai]: https://temporal.io/blog/announcing-openai-agents-sdk-integration
[temporal-polyglot]: https://temporal.io/blog/community-threads-is-it-possible-to-write-a-single-workflow-with-different
[temporal-wv]: https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning
