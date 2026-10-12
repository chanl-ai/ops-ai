# Use case runner

Status: current.

`packages/usecase-runner` (TypeScript, `@ops-ai/usecase-runner`) runs the use cases in `docs/usecases/`. It turns a
use case id and a layer into a script, runs the script, and decides PASS or FAIL from the script's output and exit
code. `scripts/usecase.mjs` is its entry and `make/usecase.mk` its make targets. It only invokes scripts: the Python
services keep pytest and the console keeps its own checks.

## Modules

| File | Does |
|---|---|
| `src/registry.ts` | Parses the Id, Service, Title, Layers, Status table in `docs/usecases/README.md`; refuses unknown layers, duplicate ids and malformed ids |
| `src/layers.ts` | The layers (api, sdk, cli, ui) and when each is available: sdk once `packages/sdk-py` or `packages/sdk-ts` exists, cli once `packages/ops-cli` exists |
| `src/resolve.ts` | Use case and layer to `docs/usecases/<service>/scripts/test-<id>-<layer>.py` or `.mjs`, or the reason there is none |
| `src/report.ts` | The output contract (`PASS <name>`, `FAIL <name>: <detail>`), the verdict, and the exit codes |
| `src/run.ts` | Spawns a script: Python in the agents-service uv project with `docs/usecases/lib` on `PYTHONPATH`, Node with the repo's node; removes model keys unless `APPROVED_REAL_CALLS=<n>` |
| `src/coverage.ts` | Per service: script, missing, not required, or not available yet, per layer |
| `src/scaffold.ts` | `new`: next id, doc from the template, registry row, docs index row, and an api script that fails until it is written |
| `src/harness.ts` | For Node (ui) scripts: checks, and `withUiStack`, which starts the agents service on the scripted model and a console dev server pointed at it |
| `src/cli.ts` | `list`, `show`, `test`, `coverage`, `new` |

## Verdict and exit codes

A script passes only when it exits 0, printed no `FAIL` line and printed at least one `PASS` line. A zero exit with
no check printed fails, so a script whose assertions never ran cannot pass.

| Exit | Meaning |
|---|---|
| 0 | Every use case that ran passed |
| 1 | A use case failed, or a layer it lists has no script |
| 2 | Usage error, unknown id, or a malformed registry |
| 3 | Nothing ran: the requested layer is not available yet |

## Tests

`pnpm --filter @ops-ai/usecase-runner verify` (or `make usecase-runner-test`) type-checks and runs
`src/runner.test.ts` with `node --test`, one test per way the runner could misreport: an unparsed or duplicated
registry row, a script that printed no check, a FAIL line with exit 0, a non-zero exit with only PASS lines, an
unavailable layer, a missing script, model keys leaking into a script, coverage mixing missing with unavailable, and a
new use case passing before it is written. The no-check test was seen failing with the guard in `report.ts` removed.

Node 22.6 or later runs the TypeScript sources directly (type stripping), so the package has no build step; its
sources use erasable syntax only.
