# runner-service: working rules

Status: current.

The runner service (`ops_runner`, :8770) runs a code tool's Python function, `main(input)` returning JSON, in a
sandbox: CPython 3.12 compiled to WASI, run by wasmtime, with a memory cap, a time limit and a call limit, no
network, an empty environment and no files beyond the run's own directory. The function reaches other systems only
through `ops.call(tool, args)`, which goes back to tools-service and is decided as the original caller's call, and
names a secret only as `ops.secret(NAME)`, a handle whose value never enters the sandbox.

It stores nothing and has no database or migrations. tools-service is its only caller (`POST /v1/runs`, service
token), at `OPS_RUNNER_URL`. Shared service rules: [services/CLAUDE.md](../CLAUDE.md). Cross-folder rules:
[root guide](../../CLAUDE.md#folder-guides).

## Code

| Path | Holds |
|---|---|
| `src/ops_runner/app.py` | `POST /v1/runs` and `/health` |
| `src/ops_runner/domain.py` | A run's limits, its result, and the host's answer to each `ops.call` |
| `src/ops_runner/wasm.py` | The wasmtime host: memory cap, epoch-based time limit, the run directory and pipes |
| `src/ops_runner/guest.py` | The guest entry, run as `/app/main.py` inside the sandbox; never imported by the runner |
| `src/ops_runner/fetch.py` | Fetches the pinned CPython WASI build into `OPS_RUNNER_CACHE_DIR` (`.data/runner`) and checks its SHA-256 |
| `tests/` | The app, loaded sources, and the sandbox walls (`test_sandbox.py`); fixtures in `tests/fixtures/` |

The Python build is not in git. `make wasm` (also run by `install`, `run` and `test`) fetches the 26 MB file once;
the service refuses to start without it or on a SHA mismatch.

## Run, test, lint

From this folder (`make help` lists every target):

| Task | Command |
|---|---|
| Fetch the pinned build | `make wasm` (the root `make runner-wasm` does the same) |
| Serve in the foreground on :8770 | `scripts/stack.sh stop runner` from the root, then `make run` (this Makefile's `stop` answers "not started") |
| Its tests (real guests on the pinned build; no database) | `make test`, or from the root `make test PKG=services/runner-service` |
| One test file | `PYTEST_ADDOPTS=tests/test_app.py make test`: this Makefile ignores `T=` |
| Lint, types | `make lint`, `make typecheck` |
| Everything | `make verify` (lint, typecheck, test; there is no OpenAPI document or gate) |
| Logs and health | from the root: `make logs SVC=runner FOLLOW=0`, `make health` |

`make api` cannot reach this service: its route answers service tokens only, and `scripts/api_as.py` has no address
for it (`SVC=runner` fails with a traceback). Exercise it through a code tool in tools-service, or through its tests.

## Rules for this service

| Rule | Detail |
|---|---|
| Walls are tested | Each wall (no socket, no host files, memory, time, call limit) has a test that fails if it falls (`tests/test_sandbox.py`) |
| No secrets, no grants | The sandbox never holds a secret's value or a grant of its own; every reach outward is an `ops.call` decided by tools-service |
| Nothing kept | A run's directory and pipes are deleted when it ends; its outcome and timings go on tools-service's call row |
| Pinned runtime | The build's URL and SHA-256 are settings (`runner_wasm_url`, `runner_wasm_sha256`); change both together |

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/runner-service/overview.md](../../docs/services/runner-service/overview.md) | Purpose, runtime, route, deploy targets, settings, walls and their tests |
| [docs/architecture/service-map.md](../../docs/architecture/service-map.md) | Where it sits |

There is no `docs/usecases/runner-service/` folder; the end-to-end check of a code tool is uc-531, registered under
tools-service (`make usecase-test UC=uc-531`).
