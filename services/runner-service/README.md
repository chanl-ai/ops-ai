# Runner service

Status: first slice (c-531). On :8770 (`make run`). No database.

Runs a code tool's Python function in a sandbox: CPython 3.12 compiled to WASI, run by wasmtime, with a memory cap, a
time limit, a call limit, no network, no environment and no files beyond the run's own. The function reaches other
systems only through `ops.call(tool, args)`, which goes back to tools-service and is decided as the original caller's
call. It names a secret only as `ops.secret(NAME)`, a handle whose value never enters the sandbox.

Only tools-service calls it (`POST /v1/runs`, service token). The Python build is not in git: `make wasm` fetches
the pinned file into `.data/runner` and checks its SHA-256, and the service refuses to start without it.

Design: `docs/services/runner-service/overview.md` and `docs/architecture/service-map.md`.
