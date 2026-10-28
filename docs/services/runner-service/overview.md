# Runner service

Status: first slice built (c-531). runner-service runs on :8770 with no database. tools-service is its only caller.
Design: `the planning repo/docs/plans/ops-ai/data-gateway-spec.md` section c; this page records what is built.

| Item | Detail |
|---|---|
| Purpose | Runs a code tool's Python function, `main(input)` returning JSON, in a sandbox that holds no network, no secrets and no grants of its own |
| Owns | Nothing stored. A run's directory and pipes are deleted when it ends; the run's outcome and timings go on tools-service's call row |
| Runtime | CPython 3.12 compiled to WASI (VMware Wasm Labs build, pinned by URL and SHA-256 in settings), run by wasmtime (`wasmtime==50.0.1`). `make -C services/runner-service wasm` fetches the 26 MB file into `OPS_RUNNER_CACHE_DIR`; the service refuses to start without it or on a SHA mismatch |
| Route | `POST /v1/runs` (service token only): `source`, `entry`, `input`, `limits`, `callToken`. Answers `ok`, `output` or `error`, `log` (last 8 KB of stderr and `print`), `calls`, `createMs`, `executeMs`, `trace` |
| Deploy | One image target, `runner` (`deploy/fly/Dockerfile`), fetches the build when the image is built. Compose: service `runner` in `deploy/compose/app.yaml`. Kubernetes: workload `runner` (`deploy/k8s/generate.py`), compiled cache under `/tmp`, 1 GiB. Fly: `[process.runner]`. tools-service reaches it at `OPS_RUNNER_URL` |
| Settings | `runner_port` 8770, `runner_url`, `runner_wasm_url`, `runner_wasm_sha256`, `runner_cache_dir`, `runner_compiled_dir` (wasmtime's compiled-module cache, default `runner_cache_dir/compiled`), `runner_concurrency` (default 2), caps `runner_max_memory_mb` 1024, `runner_max_time_s` 60, `runner_max_calls` 100 |

## Walls

| Wall | How it holds | Test |
|---|---|---|
| No network | WASI preview 1 has no sockets: `socket.socket()` raises `OSError` | `tests/test_sandbox.py::test_a_socket_cannot_be_opened` |
| No host | The guest's only directory is the run's own `/app`; its environment is empty | `test_the_host_is_out_of_reach` |
| Memory | `store.set_limits(memory_size=…)`; past it Python raises `MemoryError`, reported `memory_limit` | `test_memory_past_the_cap_stops_the_run` |
| Time | Epoch interruption: one ticker thread advances the engine's epoch every 100 ms and each store's deadline is its limit in ticks, so overlapping runs keep their own limits | `test_a_loop_past_its_time_limit_is_stopped`, `test_overlapping_runs_keep_their_own_time_limits` |
| Calls | Counted by the host, not the guest: past `limits.calls` each call is refused `call_limit` | `test_calls_past_the_limit_are_refused` |
| Secrets | `ops.secret(NAME)` is a handle sent as `{"$secret": NAME}`; the value never enters the sandbox | `test_a_secret_leaves_the_sandbox_as_a_handle` |

## How `ops.call` works

CPython in WASI cannot call host functions without ctypes, so the guest's stdin and stdout are the only channel: two
fifos in the run's directory. The prelude reads one request line, `ops.call` writes a call line and blocks on the
answer, and the run ends with one result or error line. `print` goes to stderr, the run's log, so it cannot write on
the channel. The runner answers each call by posting it to tools-service `POST /v1/code-runs/calls` with its own
service token and the run's `callToken`; tools-service decides it as the original caller's call.

## Gotchas

| Gotcha | Consequence |
|---|---|
| A trapped store holds its pipe ends until it is dropped | Every read has a deadline (`select`) and the guest thread drops the store in `finally`; without both, the host hangs after a time-limit trap |
| wasmtime's cache config has no `enabled` key in 50.x | The cache toml carries only `directory`; an `enabled` line fails engine start |
| Standard library only | No C extensions or pip packages in v1; a curated list is later work |
