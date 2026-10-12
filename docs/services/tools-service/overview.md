# tools-service

Status: current. `services/tools-service` (`ops_tools`), on :8720, with its own migration chain
(`alembic_version_tools`). Tests: `services/tools-service/tests` (registry, routes, egress, import, MCP, secrets and the
executors, against an in-process fake bank and MCP server) and `services/agents-service/tests/gateway` (the
gateway's policy, fences and approval tokens).
Design: service map row `tools-service`, [identity and tenancy](../../architecture/identity-and-tenancy.md).

## What it does

It is the one egress for tool calls and the registry behind the console's Tools pages. A tool is an operation of a
tool module; the module records who owns it, how it is reached, its versions, its security reviews and which
workflows may call which operations until when.

| Part | Detail |
|---|---|
| Registry | `/v1/tool-modules`, the console's tool-modules contract (21 operations), with the console mock's rules: approval state, views and facets, staged changes, a major change opening a security review, workflow approvals that expire and that the requester never decides, and refusal of a literal credential in a header. `POST .../reviews/{id}/decide` (not in the console's contract yet) is Security's decision; approving the current version publishes it |
| Egress | `/v1/egress`: the tenant's allow-list of hosts and private ranges, every change audited. A module's hosts are links into it. Every outbound request, discovery and calls alike, must be https on 443 to a listed host; when the connection opens, the host is resolved once, every address must be allowed (loopback, link-local and cloud metadata never; private ranges only when listed), and the connection goes to that checked address, so DNS cannot rebind between check and connect. No environment proxies, no redirects |
| Import | `discover` reads an OpenAPI 3.0 or 3.1 document (JSON or YAML) or an MCP server (initialize, tools/list over streamable HTTP) and lists every operation as a write; `operations/import`, and `create` given a `source`, re-read the source and take each operation's method, path, inputs and headers from it, the caller only picking operations and confirming reads. A re-import that no longer lists an imported MCP tool marks the module drifted, and a drifted module runs no calls |
| Secrets | `/v1/secrets`: create, rotate, delete and list. Values are AES-256-GCM encrypted with the tenant and name bound in, never returned, read on every call (a rotation reaches the next one), and scrubbed from whatever the upstream answers. Every create, rotate, delete and use is audited |
| Calls | `POST /v1/calls`. The tool resolves through the registry, which alone sets its access class. Refused before OPA and before any egress, each logged: a tool no module holds, a hidden operation, an unpublished module, input that fails the operation's schema (422 naming each field, unknown fields included), an amount over the operation's `amountMax` (403 `amount_over_limit`; 422 when the operation declares `amount` and the call leaves it out). Then OPA decides, writes need an approval token bound to the input, and writes are claimed and fenced as before. A call about to run for the first time spends one of the operation's `rateLimitPerMin`; past it the call is 429 `RATE_LIMITED` with `resetAt`, sends nothing and is logged (c-028) |
| Security reviews | A module's security review is requested by its owner and decided by Security: under any token, an approver or admin on the Security team (`security_team_id`, default `team_security`), never the requester (403 naming who decides); asking for changes needs a finding. Only the dev-header principal, which carries no roles, keeps the older rule of anyone but the requester. `view=security_review` lists modules with a pending review; each list row carries `pendingReview`. The console decides from Reviews > Tool modules or the module page (c-040) |
| Editing a call | `PATCH .../operations/{id}` takes `method`, `path`, `headers`, `body`, `responseTransform` and `timeoutMs` on an `http` operation, validated as on add: https only, the URL on the module endpoint (a second system is a second module), no literal credential in a header, a body that is a JSON template; all 400. A method, path or body change is major (it opens a security review); headers, transform and timeout are minor. While the module has pending changes, calls run the published call shape (the baseline), so an edit reaches a system only once published |
| Response transform | A Jinja2 template over the parsed, masked and scrubbed response as `data` (`ops_tools.transform`), sandboxed and strict. Protobox's transforms are Liquid: a plain `{{ data.a.b }}` means the same in both, filters differ. A template that does not parse is refused at save; one that fails on a real answer returns `{response, transform_error}` and the call still succeeds. A render is bounded: range() totals 10000 items, no string is built past 100000 characters (`*`, `%`, the padding and replace filters and str methods are sized first), and a trace stops it at 1 s on a worker thread. Secrets are scrubbed before and after it |
| Executors | `http` calls the module's endpoint: `{arg}` fills the path, a `{{arg}}` body template or the remaining arguments form the body or query, the operation's `timeoutMs` (1000 to 120000) or else the module's timeout applies, `{{NAME}}` headers are filled from secrets, and masked output paths are redacted. `mcp` calls an imported MCP tool through tools/call. `stub` answers with the operation's stub (seeded systems with no upstream). `local` runs the Runtime's demo tool of the same name |
| Failures name their side | Every failed http or MCP call carries a code and `side` (c-038). Ours: `EGRESS_DENIED`, `CONNECT_FAILED` (refused, unreachable, or the name did not resolve), `TLS_FAILED`, `CONNECT_TIMEOUT`, `POOL_TIMEOUT`. The upstream's: `UPSTREAM_TIMEOUT` (connected, no answer in time), and `RATE_LIMITED`, `INVALID_ARGUMENTS` or `UPSTREAM_ERROR` with the status it answered. Messages are fixed phrases naming the host and phase, never an address or a header value; `/v1/executions` rows carry `errorCode`, `errorMessage` and `failureSide` |
| No cookie jar | The egress client is shared by every tenant, workflow and caller, so it keeps no cookies: an upstream's Set-Cookie is dropped and never sent on a later call; only an operation's own `Cookie` header goes out (c-038, `ops_tools.egress.no_cookie_jar`) |
| Test console | `POST /v1/tool-modules/{id}/test` runs the gateway's decision. On the `stub` target it answers with the stub. On `sandbox` ("Test environment") a read is the real call: the published call shape through the same executor, egress policy, secrets and masks, with its latency and `reachedHost`; a write answers from the stub with `stubbed: true`, so the console never writes to a system. A test call spends no rate and is not in the executions log. uc-038 drives both against postman-echo.com with `OPS_LIVE_EGRESS=1` |
| Executions | `GET /v1/executions?tool&moduleId&thread&decision`: every call as the console's ToolCallRow, with `subject` (from `sub`), `actor` (from `act`), run, step, approval token fingerprint, decision and deny reason. Module activity reads the same rows |
| Traffic | Each module's and operation's `calls24h`, `errorRate` and `p95Ms` come from one aggregate over `gateway_calls` per read (`CallLog.traffic`, GROUPING SETS per operation and module), counting calls that reached the system (`ok`, `error`) in the last 24 h; refusals are `denied24h`. Activity groups the same rows into 14 UTC days (`CallLog.daily`). An approval is expiring in its last 7 days |

## Decisions

| Decision | Why |
|---|---|
| The registry is the one source of a tool's access class; the agents catalogue's tools are seeded into it as module operations run `local` | Two sources let reviews and the gateway classify one tool differently; a test fails if any catalogue tool's class differs in the registry |
| A module and its children are one aggregate written in one transaction, only against the revision read | Two concurrent edits cannot overwrite each other; the loser gets 409 |
| Keys lead with `tenant_id`; only `tool_modules` carries `team_id` | Every tenant's dev seed reuses the console's ids. Team checks run on the module; row-level security arrives with `ops_identity` |
| Schema validation happens in the gateway, before OPA | Protobox never validated input on execute; the console's test console promises per-field errors |
| The call log keeps a fingerprint of an approval token (`apt:` + 32 hex), never the token | The log identifies which approval allowed a write without holding bearer material |
| Locally run tools validate against the Runtime's input, not the console seed's picture of them | The seed's `send_reply` and `place_wire_hold` fields differ from what the Runtime sends |
| The dev seed refreshes modules nobody has edited (revision 0) and leaves edited ones | A changed seed reaches an existing dev database without erasing anyone's work |
| The egress check runs inside the connection (httpcore's network backend), not before the request | Checking a name and then letting the client resolve it again lets DNS answer differently in between; a test shows the old shape dialling 10.0.0.5 |
| Private ranges are reachable only when listed; loopback, link-local and metadata never | A bank's own systems sit on private addresses, so a blanket deny forbids the product's main use; listing both host and range keeps the metadata endpoint and stray internal hosts out |
| Imported operations are writes until the owner confirms a read | A name that looks like a read proves nothing; a wrong guess would run a write without an approval token |
| A secret is bound to its tenant and name in the encryption, and resolved values are scrubbed from outputs | A ciphertext copied under another name fails to decrypt, and an upstream that echoes headers cannot carry the value into the call log |
| Workflows are agents-service's: tools-service reads them on `GET /v1/internal/workflows` with its service token, caches each tenant's list for 30 s, and answers 503 `workflows_unavailable` when agents-service cannot be reached | A fixture list refused every real workflow, and a fallback would decide an approval on data that is not there (c-039) |
| An approval records its workflow's owning team when requested; a team id tools-service has no record of is refused 422 | Visibility checks stay synchronous, and a workflow nobody here owns must not fall to the all-scope team, which would let any team decide it (c-039) |
| The test console runs as a workflow with sample values the builder types, not fixture cases | Real cases need agents-service to expose each thread's case fields (c-039) |
| An operation's rate limit is counted per tenant and operation in Postgres (`operation_rate_windows`), one atomic upsert per call, in fixed one-minute windows on the database clock; only a first execution that passed every other check spends one | The limit protects the upstream, which sees one caller whatever workflow asked, and the count must hold across gateway processes and restarts; refusals and replays spending slots would make the limit stricter than set. A window edge can let 2N through in 60 s (c-028) |
| The amount limit reads the operation's `amount` input, in one function the gateway and the test panel share (`ops_tools.limits`); an amount limit on an operation without one is refused at save | Two copies let the panel and real calls disagree; a limit with nothing to read is shown and never holds (c-028) |
| Staged call-shape edits are not live; calls read the baseline while changes are pending | Staged operation edits apply in place, so an edited path would otherwise run before publish and, when major, before Security's review (c-027) |
| A transform sees the response already scrubbed | Scrubbing only the rendered output let `reverse`, `join` or a key lookup into an error re-encode a secret past it (c-027 review) |
| A transform's strings are sized before they are built | A trace deadline cannot interrupt one C-level call; `"a"|center(300000000)` took 1.5 GB before any check (c-027 review) |

## Not yet

| Gap | Where it lands |
|---|---|
| Uploading a spec file (`fileId`), MCP over stdio, a key management service behind the cipher port | Later cards |
| Caller identity: one tenant (`local`), the dev user, team from `X-Team-Id`, `X-Dev-User` honoured in dev only; roles for the allow-list, secrets and review decisions; RLS on the registry; audit entries in platform-service | c-006 and its adoption card |

| Teams and connections come from the dev seed (`services/tools-service/seed/`), which the console's mock exports; a backend seed taken from a UI mock runs backwards | Teams from platform-service, connections from their own service |
| The agents-service workflow registry is not partitioned by tenant; its internal route serves every row to any tenant-scoped service token | Tenancy on the registry tables |

## Run and check

| Task | Command |
|---|---|
| Serve on :8720, seeded in dev | `make run-tools` |
| Lint, types, tests, OpenAPI gate | `make -C services/tools-service verify` |
| Gateway tests | `make -C services/tools-service test-gateway` |
| Regenerate `openapi.json` | `make -C services/tools-service openapi` |
| Use cases | `make usecase-test UC=uc-010`, `UC=uc-011`, `UC=uc-012`, `UC=uc-013`, `UC=uc-007` (uc-012 and uc-013 need a private network address for their fake bank) |
| Settings | `OPS_SECRETS_KEY` (64 hex; the dev default is refused outside dev), `OPS_EGRESS_CA_FILE` (an internal CA to trust), `OPS_EGRESS_RESOLVE` (dev only: fixed answers for names, used by the use cases) |
