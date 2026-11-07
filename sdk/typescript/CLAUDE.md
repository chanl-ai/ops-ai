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
