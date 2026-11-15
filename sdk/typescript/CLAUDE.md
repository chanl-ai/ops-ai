# TypeScript SDK: working rules

Status: current.

The `@chanl-ai/ops-ai` package: `OpsAI` over the public API, built to `dist/` with `tsc`. The console depends on it as
a workspace package and type-checks against `dist/`, so rebuild after regenerating. Shared SDK rules, the generator and
every command: [../CLAUDE.md](../CLAUDE.md). User guide: [docs/sdk/typescript.md](../../docs/sdk/typescript.md).

| Path | Holds |
|---|---|
| `src/generated/` | Written by `sdk/generate.py` (types by openapi-typescript); never edited |
| `src/client.ts` | `OpsAI`, `Raw`, `Resource` and the nouns |
| `src/agents.ts`, `workflows.ts`, `words.ts` | Agents, workflows (`WorkflowCheck`), apps, credentials, accounts, tools, resources, usage |
| `src/transport.ts`, `errors.ts` | HTTP, server events, the error classes |
| `test/` | `node --test` suites; no stack |
| `examples/run-and-decide.mjs` | Starts a run and decides its task on the local stack; `make sdk-check` runs it |

| Task | Command (repo root) |
|---|---|
| Build (`dist/`) | `pnpm --filter @chanl-ai/ops-ai build` |
| Build and tests | `pnpm --filter @chanl-ai/ops-ai test` |

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [console, SDKs and CLI](../../docs/architecture/standards/console-and-sdk.md) (`UI1` to `UI7`), [API contracts and models](../../docs/architecture/standards/api-and-models.md) (`AP1` to `AP7`, `MD1` to `MD4`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
