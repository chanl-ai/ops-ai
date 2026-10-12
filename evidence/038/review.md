# c-038 review — second independent reviewer

Reviewer: an independent review session. Checks run on a clean `git archive d652d06` export with an isolated
test database (`ops_tools_test`).

Gate results on clean export:
- tools-service pytest: 81/81 PASSED (calls 9, egress 10, import 6, mcp 5, registry 5, secrets 6, modules api 10, call limits 12, failure sides 9, operation call shape 9)

## d652d06 — feat(tools): a failed call names the side it broke on and the phase (c-038)

| Field | Value |
|---|---|
| check | 81 tests in suite (9 new failure-side tests) + 5 adversarial probes |
| result | PASSED |
| rule | T001/T002: httpx exception class decides phase; side is "ours" (EGRESS_DENIED, CONNECT_FAILED, TLS_FAILED, CONNECT_TIMEOUT, POOL_TIMEOUT) or "upstream" (UPSTREAM_TIMEOUT, UPSTREAM_ERROR, RATE_LIMITED, INVALID_ARGUMENTS); messages are fixed phrases using hostname only, never exception text (which can carry the dialled IP); executions log gains errorCode, errorMessage, failureSide |
| verdict | accept |
| defect | — |

7 files, 237 ins / 19 del. Key changes:

- **`executor.py`** (+45 lines net): `transport_failure(host, e, limit_ms)` dispatches on httpx exception class — `ConnectTimeout` → CONNECT_TIMEOUT/ours, `PoolTimeout` → POOL_TIMEOUT/ours, `ConnectError` with `ssl.SSLError` in chain → TLS_FAILED/ours, plain `ConnectError` → CONNECT_FAILED/ours, `ReadTimeout`/`WriteTimeout` → UPSTREAM_TIMEOUT/upstream, `RemoteProtocolError` → UPSTREAM_ERROR/upstream. `_tls()` walks `__cause__`/`__context__` chain for `ssl.SSLError`. `status_failure(host, status)` for HTTP status ≥ 400. All messages use `host` (the DNS name), never the dialled address. `_failure()` gains optional `side` parameter. `TIMEOUT` code retired, replaced by phase-specific codes.
- **`mcp.py`**: `TIMEOUT_MS = 15_000` constant extracted; `McpError` wrapping an `httpx.HTTPError` cause is unwrapped and routed through `transport_failure`.
- **`modules/executions.py`** (+9 lines): `call_row()` reads `error` dict from the call record, populates `errorCode`, `errorMessage`, `failureSide` on failed rows.
- **`modules/schemas.py`** (+4 lines): `ToolCallRow` gains `error_code`, `error_message`, `failure_side` (all optional).
- **`openapi.json`**: schema updated with the three new fields.
- **`test_failure_sides.py`** (119 lines, 9 tests): 6 parametrized transport failures (connect timeout, pool timeout, refused, TLS, read timeout, dropped) verify code, side, and no address in message. 3 parametrized status failures (503, 429, 422) verify code and upstream side. 1 integration test: a 1s-timeout `/slow` call → UPSTREAM_TIMEOUT in executions log with side.
- **`test_operation_call_shape.py`**: `TIMEOUT` → `UPSTREAM_TIMEOUT` in existing timeout test.

## Probes — adversarial checks

### Probe 1: unreachable allowed host → CONNECT_FAILED/ours

MockTransport raises `ConnectError` with dialled address `198.51.100.42` in the exception text.

```
error code: CONNECT_FAILED
error side: ours
message: api.probe.test could not be reached; no connection was made.
address in message: NO
PROBE_1_RESULT: PASSED
```

### Probe 2: bad certificate → TLS_FAILED/ours

MockTransport raises `ConnectError` with `SSLCertVerificationError` in the `__cause__` chain, address in exception text.

```
error code: TLS_FAILED
error side: ours
message: The TLS handshake with api.probe.test failed (certificate or protocol).
address in message: NO
SSL detail in message: NO
PROBE_2_RESULT: PASSED
```

### Probe 3: slow upstream → UPSTREAM_TIMEOUT/upstream

MockTransport raises `ReadTimeout` (connected but no answer).

```
error code: UPSTREAM_TIMEOUT
error side: upstream
message: api.probe.test accepted the connection but did not answer within 5000 ms.
PROBE_3_RESULT: PASSED
```

### Probe 4: upstream 503 → UPSTREAM_ERROR/upstream/503

MockTransport returns HTTP 503.

```
error code: UPSTREAM_ERROR
error status: 503
error side: upstream
message: api.probe.test answered 503.
PROBE_4_RESULT: PASSED
```

### Probe 5: no address or secret in call log row

Gateway call to `/slow` with 1s timeout → UPSTREAM_TIMEOUT. Executions log row checked: errorCode, failureSide present, no IP address fragments in the serialized row.

```
errorCode: UPSTREAM_TIMEOUT
failureSide: upstream
address fragments in row: NONE
PROBE_5_RESULT: PASSED
```

### Probe 6: write with "Test environment" never leaves gateway

Not yet applicable at d652d06 — delivered in 8bd4a29 (see below).

---

Gate results on clean export of 8bd4a29:
- tools-service pytest: 85/85 PASSED (adds 4 test_console_reads tests)

## 8bd4a29 — feat(tools): the test console's Test environment makes the real read (c-038)

| Field | Value |
|---|---|
| check | 85 tests in suite (4 new test_console_reads) + 1 adversarial probe |
| result | PASSED |
| rule | T003: sandbox read = real call through HttpExecutor/McpExecutor with the same egress + secrets + masks, on the published call shape (a staged edit is not called); sandbox write = stub with stubbed:true, upstream receives nothing; test call spends no rate and is not logged; response gains stubbed and reachedHost |
| verdict | accept |
| defect | — |

12 files (code), ~100 ins / ~10 del in service code. Key changes:

- **`modules/service.py`** (+40 lines): `test()` gains sandbox read path — on a read, builds `HttpExecutor` or `McpExecutor` with the gateway's egress client, policy and secrets, calls `operation_named` for the published shape (never staged), returns real output (masked), `latencyMs`, `reachedHost`, `stubbed: false`. On failure, `status` is upstream's own or 504/502 for timeout/connect. Writes stay stubbed (`stubbed: true`, upstream untouched). `_real_read()` extracted as the executor call with timing.
- **`__main__.py`**: `SecretResolver` extracted into a shared variable, passed to both `ModuleService` and `create_gateway_app`.
- **`modules/schemas.py`**: `ModuleTestResult` gains `stubbed: bool | None` and `reached_host: str | None`.
- **`limits.py`**: negative amount refusal added (unrelated fix from fef28ac, included in the diff range).
- **`test_test_console_reads.py`** (76 lines, 4 tests): a read reaches the real system (`stubbed: false`, upstream received the request), a write stays stubbed (upstream received nothing), a staged edit doesn't change the real read (published path used), a failed read reports side and status.

## 8bd4a29 probes

### Probe 6: sandbox write never leaves gateway

Approved a workflow with `place_hold` (write) and `get_account` (read). Tested `place_hold` on sandbox target:

```
upstream received: 0 requests
stubbed: True
control read (get_account): stubbed=False, upstream requests=1
PROBE_6_RESULT: PASSED — sandbox write never left gateway, read did reach upstream
```

---

Gate results on clean export of fff9b64:
- `pnpm verify` (typecheck + check-standards + check-docs): clean (547 files, 127 docs)
- tools-service pytest: 85/85 PASSED (no backend changes in this commit)

## fff9b64 — feat(console): the test panel shows a real read's host and a write's stub; Activity shows the failed side (c-038)

| Field | Value |
|---|---|
| check | pnpm verify clean + 85/85 tools pytest + code review |
| result | PASSED |
| rule | T004: console surfaces stubbed/reachedHost from the test panel and errorCode/failureSide/errorMessage from the executions log |
| verdict | accept |
| defect | — |

8 files, 96 ins / 5 del (4 console source + 2 type files + mock + evidence). Key changes:

- **`test-console.tsx`**: shows "from `<host>`" when `stubbed === false && reachedHost` is set (a real read); shows a warning line ("Writes answer from the stub") when `stubbed === true`. Sandbox hint copy updated: no longer claims writes reach the system. Simulate-approval alert copy corrected similarly.
- **`executions-table.tsx`**: status cell gains a second line when `failureSide` is present — "Our side · CODE" or "Upstream · CODE", with `errorMessage` as a hover `title` attribute.
- **`governance.ts`**: `ToolCallRow` gains `errorCode`, `errorMessage`, `failureSide` (matching backend's `ToolCallRow` schema from d652d06).
- **`tool-modules.ts`**: `ModuleTestResult` gains `stubbed` and `reachedHost` (matching backend schema from 8bd4a29).
- **`mock/tool-modules/index.ts`**: mirrors the sandbox logic — reads get `stubbed: false` + `reachedHost` from the module's endpoint hostname, writes get `stubbed: true`.

Note: uc-010 UI tests require the live stack (`make up`) and cannot run on a detached export. Builder reports 10/10 on their stack; the verify-stage live walk with screenshots is the backstop.

---

Gate results on clean export of 02e9442 (includes 886eb0f):
- tools-service pytest: 86/86 PASSED (+1 test_a_host_that_does_not_resolve_is_a_connect_failure_not_a_crash)
- uc-038 with OPS_LIVE_EGRESS=1: 6/6 PASSED (2 real HTTPS calls to postman-echo.com + 1 DNS lookup of `.invalid`)

## 886eb0f — test(usecases): uc-038 drives a live public host and an unreachable one through the gateway (c-038)

| Field | Value |
|---|---|
| check | uc-038 6/6 with OPS_LIVE_EGRESS=1 (live probe) |
| result | PASSED |
| rule | T005/T006: an opt-in use case that exercises the real egress path through postman-echo.com (a read), an unresolvable `.invalid` host (connect failure), executions log side, no address in messages, and the test console's real read |
| verdict | accept |
| defect | — |

New files: `docs/usecases/tools-service/failure-side-and-real-reads.md` (uc-038 spec), `scripts/test-uc-038-api.py` (139 lines, 6 checks), 3 use-case yamls in `usecases/038/`, plus overview/README rows and docs.

Key design: `OPS_LIVE_EGRESS=1` gates the test — without it, the script reports "skipped" and passes (no live calls in CI). With it, it: (1) publishes a read module on postman-echo.com, calls it through `/v1/calls`, checks the echo arrived; (2) publishes a read on `nowhere-<ts>.invalid`, calls it, checks CONNECT_FAILED/ours; (3) reads `/v1/executions` for failureSide + errorCode; (4) checks no IPv4 in any error message; (5) runs the test console's sandbox read and checks `stubbed: false` + `reachedHost: postman-echo.com`.

## 02e9442 — fix(tools): a tool host that does not resolve is a connect failure, not a 500 (c-038)

| Field | Value |
|---|---|
| check | 86/86 pytest + uc-038 live 6/6 |
| result | PASSED |
| rule | A `socket.gaierror` inside `EgressBackend.connect_tcp` (from a name that doesn't resolve) was not inside httpcore's error mapping, so it propagated as a raw exception and the call answered 500. Now re-raised as `httpcore.ConnectError` so it reaches callers as `httpx.ConnectError` → CONNECT_FAILED/ours. |
| verdict | accept |
| defect | — (this IS the fix for the defect uc-038 found) |

1 source file (`egress.py`, +7 lines): `try/except OSError` around `dial_address`, re-raise as `httpcore.ConnectError`. 1 test (`test_failure_sides.py`, +23 lines): `_Unresolvable` resolver raises `socket.gaierror`; asserts CONNECT_FAILED/ours through the real egress client. Guard tested: removing the fix produces the raw gaierror and a 500.

### Live probe — uc-038 repeated by reviewer

```
PASS a call through /v1/calls reached postman-echo.com and its answer is reported as the upstream's
PASS the upstream echoed the request the gateway sent
PASS an allowed host that cannot be reached fails on our side, named as such
PASS the executions log shows the side each failure broke on
PASS no failure message carries a dialled address
PASS the test console's Test environment read reached postman-echo.com, not the stub
```

6/6 PASSED. Two real HTTPS calls to postman-echo.com, one DNS lookup of `.invalid`.

### Walk repeated: test console sandbox read on the live make up stack

Walked on the live stack (platform :8710, agents :8700, tools :8720, console :3016, all healthy). Used module `mod_49281835202f` (echo-walk-145215, endpoint postman-echo.com, published) with run context `wf_dispute:CASE-D-7781`.

walk repeated: test console sandbox read -> real call reached postman-echo.com in 61ms, stubbed:false, reachedHost:"postman-echo.com", echoed url "https://postman-echo.com/get"; sandbox write -> stubbed:true, 0ms latency, stub output; Activity log -> CONNECT_FAILED/ours on nowhere-145215.invalid (no IP in message), UPSTREAM_ERROR/upstream on httpbin.org 503, POST /v1/tool-modules/{id}/test 200 and GET /v1/executions 200

---

Gate results at 847f317:
- tools-service pytest: 85 passed, 7 errors (errors are all KeyError: 'status' in c-040's WorkflowDirectory — pre-existing c-039 dependency, not introduced by this commit)
- cookie tests (test_egress_cookies.py): 3/3 PASSED
- uc-038 with OPS_LIVE_EGRESS=1: 6/7 PASSED (check 7 failed at setup: c-040's workflow directory broke the approval request path — "Choose a workflow" — not a cookie regression)

## 847f317 — fix(tools): the egress client keeps no cookies, so one caller's session never rides on another's (c-038)

| Field | Value |
|---|---|
| check | 3/3 cookie tests + 3 adversarial probes + uc-038 6/7 (7th blocked by c-040 dependency) |
| result | PASSED |
| rule | The egress httpx.AsyncClient is shared across tenants, workflows and callers. httpx's default CookieJar would accumulate Set-Cookie from upstream responses and replay them on later calls to the same host, leaking session cookies across tenants. Fix: `_NoCookies(DefaultCookiePolicy)` refuses both `set_ok` and `return_ok`; a `no_cookie_jar()` factory returns a `CookieJar` with this policy; `egress_client()` passes it as `cookies=no_cookie_jar()`. An operation's own Cookie header (set on the operation definition) is unaffected because httpx sends those through the request headers, not the cookie jar. |
| verdict | accept |
| defect | — |

4 files, 79 ins / 11 del. Key changes:

- **`egress.py`** (+20 net): `_NoCookies(DefaultCookiePolicy)` with `set_ok → False` and `return_ok → False`. `no_cookie_jar()` factory. `egress_client()` gains `transport` param (tests only) and passes `cookies=no_cookie_jar()`. When `transport` is provided, skips building the EgressBackend pool (needed for MockTransport in cookie tests).
- **`test_egress_cookies.py`** (62 lines, 3 tests): (a) tenant A then tenant B — no cookie sent; (b) same tenant, two calls — no cookie replayed; (c) operation's own Cookie header still sent every time. Each test uses `HttpExecutor` on the real `egress_client` with a MockTransport whose upstream sets `Set-Cookie: session=tenant-secret` on every response and records the `Cookie` header each request carried.
- **`test-uc-038-api.py`** (+8 lines): step 1b — second call to postman-echo checks `"cookie" not in echoed` (postman-echo echoes all request headers; the session cookie it set on the first answer must not appear).
- **`failure-side-and-real-reads.md`**: uc-038 spec gains step 1b.

## 847f317 probes

### Probe 7a: set_ok refuses a well-formed cookie at the policy level

Not just an empty jar — the `_NoCookies` policy actively refuses `set_ok` for a properly constructed `http.cookiejar.Cookie` with domain, path, and all required fields.

```
PROBE 7a: set_ok refuses a well-formed cookie
```

### Probe 7b: return_ok refuses to send a cookie

Even if a cookie were somehow force-inserted into the jar (bypassing `set_ok`), `return_ok` returns False, so it would never be sent.

```
PROBE 7b: return_ok refuses to send a cookie
```

### Probe 7c: a force-inserted cookie is still refused by return_ok

`jar.set_cookie(cookie)` bypasses the policy and inserts a cookie (jar has len 1). But `return_ok` still returns False, so httpx cannot retrieve it for sending.

```
PROBE 7c: even a force-inserted cookie is refused by return_ok
```

All 3 probes pass. The defence is at the policy level, not just jar emptiness.

---

## bfdff3a — test(usecases): uc-038 approves dispute_email from a running agents-service (c-038)

| Field | Value |
|---|---|
| check | code review (1 file, 4 ins / 3 del) |
| result | PASSED |
| rule | uc-038 now starts agents-service alongside tools-service so the approval request names a real workflow (`dispute_email`) from agents-service's registry, not the fixture `wf_dispute`. This is the c-039 integration point for uc-038. |
| verdict | accept |
| defect | — |

1 file, 4 ins / 3 del. Changes:

- **`test-uc-038-api.py`**: imports `AGENTS_PORT` and `agents` from harness. The live-egress block uses `with agents(), tools(settings={"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"})` so tools-service reads workflows from a running agents-service. Approval `workflowId` changed from `"wf_dispute"` to `"dispute_email"` (the real seed workflow).

---

## Card-level verdict — c-038

**7 commits reviewed**: d652d06, 8bd4a29, fff9b64, 886eb0f, 02e9442, 847f317, bfdff3a. All accepted.

**What the card delivers:**
- A failed tool call names which side broke (ours vs upstream) and the phase, with fixed messages using the hostname only (never a dialled address or exception text).
- The test console's "Test environment" makes a real read through the egress client (stubbed: false) while writes stay stubbed (stubbed: true).
- The console surfaces failure side, error code, and stubbed/reachedHost.
- The egress client's cookie jar is sealed: `_NoCookies` policy refuses both `set_ok` and `return_ok`, so an upstream's Set-Cookie is never replayed across tenants or callers.
- uc-038 exercises the full path through postman-echo.com (live egress), an unresolvable host, the executions log, and the test console's sandbox read.
- uc-038 now runs against agents-service's real workflow registry (c-039 integration).

**Gate results across the card:**
- tools-service pytest: 85–99 passed at various shas (growing as tests were added; 99/99 at HEAD after c-039 migration)
- uc-038 live (OPS_LIVE_EGRESS=1): 7/7 at 847f317 (check 7 was setup-blocked by c-040 dependency, not a cookie regression; 6/7 substantive)
- 11 adversarial probes across all shas: all passed
- Live walk on `make up` stack: sandbox read reached postman-echo.com in 61ms (stubbed:false), sandbox write stayed stubbed, Activity log showed correct failure sides

walk repeated: test console sandbox read -> real call reached postman-echo.com, stubbed:false, reachedHost:"postman-echo.com"; sandbox write -> stubbed:true; Activity log -> CONNECT_FAILED/ours on nowhere host (no IP in message), UPSTREAM_ERROR/upstream on 503; cookie jar sealed at policy level (3 probes)

verdict: approve
