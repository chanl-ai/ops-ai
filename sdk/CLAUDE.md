# SDKs: working rules

Status: current.

This folder holds the two client libraries for the platform's public API and the generator that keeps them in step
with the services: `python/` (the `ops-ai` package, import `ops_ai`, with the `opsai` command line) and `typescript/`
(`@chanl-ai/ops-ai`). They sit between the services and the console and CLI in the onion
([Onion order](../CLAUDE.md#onion-order)): a route lands in a service first, then here, then in a screen or command.
Guides for users of the SDKs: [docs/sdk/python.md](../docs/sdk/python.md), [docs/sdk/typescript.md](../docs/sdk/typescript.md).

## Two layers

| Layer | Python | TypeScript | Written by |
|---|---|---|---|
| Generated: one method per public operation, request and response types | `python/src/ops_ai/_generated/<service>/` | `typescript/src/generated/<service>.ts`, `<service>-operations.ts` | `generate.py` from each `services/<x>/openapi.json`; never edited by hand |
| Hand-written: the client, nouns (`runs`, `tasks`, `agents`, `workflows` and the rest), waits, streams, errors | `python/src/ops_ai/_client.py`, `_agents.py`, `_workflows.py`, `_words.py`, `errors.py` | `typescript/src/client.ts`, `agents.ts`, `workflows.ts`, `words.ts`, `errors.ts` | people |
| Command line `opsai` (`login`, `workflows`, `agents`, `resources`, `plugin`) | `python/src/ops_ai/cli.py`, `_cli/` | none | people; each verb calls the client's methods, never the API directly |

Only operations a service marks `x-ops-public: sdk` or `both` are generated, and the auth headers every route declares
are dropped because the client sends them on each call (`generate.py`, docstring; the marker is described in
[docs/architecture/api.md](../docs/architecture/api.md)). Any public operation without a hand-written method is still
reachable as `ops.raw.<service>.<operation>(...)`, which is how the console's screens on the SDK call it
(`apps/console/src/lib/api/ops-sdk.ts`).

## Commands

Run from the repo root.

| Task | Command |
|---|---|
| After a route or DTO change: every service's `openapi.json`, then both SDKs | `make openapi` |
| Regenerate only the SDKs from the committed documents | `make sdk` |
| Generated layer matches the documents (no stack, seconds) | `uv run python sdk/generate.py --check` |
| Python tests | `uv run --isolated --quiet --with pytest --with-editable sdk/python pytest -q sdk/python/tests` |
| TypeScript build and tests (rewrites `typescript/dist/`, which the console type-checks against) | `pnpm --filter @chanl-ai/ops-ai test` |
| All three, as `make verify` runs them | `make sdk-verify` (`SDK_REF=HEAD` reads the documents as committed) |
| The packages installed in an empty folder, then the examples on the live stack | `make sdk-check` (`SDK_LIVE=0` skips the stack part) |
| One call as a seeded person on the stack | `make sdk-call CALL='ops.raw.platform.me_me()' AS=builder` ([Calling the API as a person](../CLAUDE.md#calling-the-api-as-a-person)) |
| The command line from this checkout | `uv run opsai --help` |

`sdk/python` is a member of the root uv workspace, so `uv run opsai --help` from the root runs the command line on
this checkout. Its tests run in an isolated environment (`--isolated --with-editable sdk/python`) so they see only
what the package itself declares, as an outside developer's install would.

## Rules

| Rule | Detail |
|---|---|
| The documents are the source | A method is missing or wrong because the service's route or its `x-ops-public` marker is; fix the service and run `make openapi`, never the generated files |
| Both languages move together | The hand-written nouns match one for one (`python/src/ops_ai/_words.py` and `typescript/src/words.ts` define the same classes); a noun or verb added to one is added to the other in the same change. The CLI is Python only |
| No stack in unit tests | `python/tests` and `typescript/test` run without services; the live examples (`python/examples/seed_team.py`, `typescript/examples/run-and-decide.mjs`) run only under `make sdk-check` |
| Publishing | `.github/workflows/sdk-publish.yml` builds and dry-runs both packages; it publishes only when the repository variable it names is set |

Changes here are `feat(sdk)` or `fix(sdk)` commits; they need no What's new entry unless they also change `apps/` or
`services/` ([Commits](../CLAUDE.md#commits)).
