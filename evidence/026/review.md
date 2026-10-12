# c-026 review — second independent reviewer

Reviewer: an independent review session. Checks run on a clean `git archive 6132606` export with isolated databases
and ephemeral ports (the harness picks them).

Gate results on clean export:
- tools-service pytest: 28/28 PASSED (calls 9, egress 4, registry 5, modules api 10)
- `make usecase-test UC=uc-010 LAYER=api`: 11/11 PASSED
- `make usecase-test UC=uc-011 LAYER=api`: 8/8 PASSED

## 6132606 — feat(tools): one tenant egress allow-list; module hosts must be on it

| Field | Value |
|---|---|
| check | tools-service 28 tests + uc-010 (11) + uc-011 (8) + 4 adversarial probes |
| result | PASSED |
| rule | US4: hosts off the tenant allow-list are refused naming the host; public/loopback/link-local ranges refused; module hosts are FK links into the list; host in use cannot be removed (409); every change audited in the same transaction; migration reversible |
| verdict | accept |
| defect | — |

20 files, 1519 ins / 22 del. Key additions:

- **`egress.py`** (43 lines): `listable_host` validates bare lowercase DNS names (IP addresses refused — list as range), `listable_range` validates private CIDR (loopback, link-local, multicast, public all refused; CGNAT included as private).
- **`egress_routes.py`** (138 lines): `/v1/egress` CRUD — `GET` returns hosts (with which modules use each) and ranges, `POST /hosts` and `/ranges` add entries, `POST /hosts/remove` and `/ranges/remove` remove them. Add is audited, idempotent (200 on duplicate). Remove refuses with 409 + `modules` list when a module uses the host. `caller` dependency respects `dev_headers` flag (c-007 pattern).
- **`store/egress.py`** (138 lines): `EgressStore` with `TRANSACTION` guarantee. `add` uses `begin_nested()` + `IntegrityError` catch for idempotent upsert; audit row in the same transaction. `remove` checks `module_egress_hosts` first, raises `HostInUseError` with module list before deleting. `host_allowed` and `ranges` for executor/discovery use.
- **`store/modules.py`** changes: `egress_hosts` JSON column removed from `tool_modules` table. `module_egress_hosts` link table with composite FK to `egress_hosts(tenant_id, host)` (RESTRICT) and `tool_modules(tenant_id, id)` (CASCADE). `put()` checks all hosts against `_listed_hosts` before writing — `HostNotAllowedError` on first unlisted host. `_children()` now reads `module_egress_hosts` alongside operations/versions/reviews/approvals.
- **`modules/service.py`**: catches `HostNotAllowedError` in both `_save` and `_create`, surfaces as `Unprocessable` with `egress_host_not_allowed` code naming the host.
- **`modules/seed.py`**: seed now lists its modules' hosts on the tenant egress list first (`EgressStore.add` per host), so the FK constraint is satisfied.
- **Migration `0004_egress_allow_list.py`** (103 lines): creates `egress_hosts`, `egress_ranges`, `egress_audit`, `module_egress_hosts` tables. Migrates existing JSON hosts with `json_array_elements_text` — inserts into tenant list and links, with audit rows. `DISTINCT ON` handles duplicate hosts across modules. Downgrade restores JSON column from links via `json_agg`, drops new tables.
- **Tests** (`test_egress.py`, 113 lines): 4 tests — module names only listed hosts (422→list→200), host in use stays listed (409 naming module) with audit trail, only private ranges listable (public/loopback/link-local/address all refused), migration up/down/up roundtrip on a scratch database.
- **Existing tests updated**: `test_calls.py` adds host to egress list before creating module; `test_registry_store.py` passes empty `egress_hosts` to avoid FK; `test_tool_modules_api.py` lists host before adding operation with it.

## Probes — adversarial checks

### Probe 1: add a public range (refused)

```
status: 400
error: 8.8.8.0/24 is public. Only private networks are listed; public hosts need no range.
PROBE_1_RESULT: PASSED — public range refused
loopback_status: 400 (127.0.0.0/8 refused)
linklocal_status: 400 (169.254.0.0/16 refused)
```

### Probe 2: name an unlisted host on a module (422)

```
status: 422
code: egress_host_not_allowed
message: reports.notlisted.com is not on the egress allow-list. An admin adds it under Egress before a module can call it.
names_the_host: True
PROBE_2_RESULT: PASSED
```

### Probe 3: remove a host in use (409)

Listed `reports.example.com`, added an operation on `mod_document_service` using it, then tried removing it.

```
status: 409
message: reports.example.com is called by mod_document_service. Change those modules first.
modules: ['mod_document_service']
names_the_module: True
PROBE_3_RESULT: PASSED
```

### Probe 4: migration tools_0004 up, down, up

Inserted a module with `["api.one.test", "api.two.test"]` at tools_0003, then ran up/down/up.

```
UP1 hosts: ['api.one.test', 'api.two.test']
UP1 links: ['api.one.test', 'api.two.test']
UP1 audit: 2
UP1 json_col_gone: True
DOWN hosts_json: ['api.one.test', 'api.two.test']
DOWN egress_table_gone: True
UP2 hosts: ['api.one.test', 'api.two.test']
UP2 links: ['api.one.test', 'api.two.test']
UP2 audit: 2
PROBE_4_RESULT: PASSED — migration up/down/up preserves data
```

---

Gate results on clean export of 1a0cd19 (HEAD of the c-026 range):
- tools-service pytest: 40/43 PASSED, 2 failed (OPA-dependent approval token tests, unrelated to egress), 1 error (MCP off-list, unrelated)
- egress tests (6): PASSED, import tests (5): PASSED, MCP tests (4/5): PASSED
- alembic migration to HEAD required on the shared test database (egress tables were new)

## 642aa65 — feat(tools): egress policy resolves once and dials only the address it checked

| Field | Value |
|---|---|
| check | 6 new egress tests in suite + 2 adversarial probes (DNS rebinding, private outside range) |
| result | PASSED |
| rule | US4: DNS cannot rebind between check and connect; private addresses outside listed ranges refused; loopback/link-local/metadata/CGNAT denied even with covering ranges; only https on 443 to listed hosts; egress client has no proxies and no redirects |
| verdict | accept |
| defect | — |

7 files, 292 ins / 15 del. Key additions:

- **`egress.py`** (+107 lines): `ALWAYS_DENIED` (169.254.169.254/32, fd00:ec2::254/128 — cloud metadata). `Resolver` protocol with `SystemResolver` (getaddrinfo). `address_allowed()` — loopback/link-local/multicast/unspecified/metadata never; private/CGNAT/reserved only in listed range; IPv4-mapped IPv6 unwrapped first; public always. `EgressPolicy` with `check_url` (https, port 443, listed host) and `dial_address` (resolve once via injected resolver, check ALL addresses, return first). `EgressBackend(httpcore.AsyncNetworkBackend)` — `connect_tcp` reads `CURRENT_TENANT` contextvar, calls `dial_address`, connects to the checked address; `connect_unix_socket` raises. `egress_client()` builds httpx.AsyncClient with custom pool on `EgressBackend`, no proxies (`trust_env=False`), no redirects.
- **`executor.py`**: `HttpExecutor.__init__` takes `policy: EgressPolicy | None`. `run()` sets `CURRENT_TENANT`, calls `policy.check_url` before HTTP. `McpExecutor` not yet (next commit).
- **`app.py`**: `create_gateway_app` takes `egress` param, creates `egress_client(egress)` as default.
- **Tests** (`test_egress.py`, +127 lines): `ScriptedResolver` and `RecordingNetwork` (raises `Dialled` instead of connecting). 6 tests: DNS rebinding caught (resolved once, dialled checked address), private outside range refused (including IPv4-mapped IPv6, CGNAT, metadata), listed range connects, unlisted host refused before resolution, URL check (only https/443/listed), loopback/link-local/metadata denied even with covering ranges.

## 642aa65 probes

### Probe 5: scripted resolver answers public then 10.0.0.5 — refused

```
REFUSED: EgressDenied: safe.example.com resolves to an address tools-service may not reach.
PROBE_5_RESULT: PASSED — refused because resolved addresses include a private one outside listed ranges
```

### Probe 6: allowed host resolving to private outside listed range — refused

Listed host `internal.corp.example` and range `172.16.0.0/12`. Resolver returns `10.0.0.5` (10/8, not in 172.16/12).

```
REFUSED: EgressDenied: internal.corp.example resolves to an address tools-service may not reach.
PROBE_6_RESULT: PASSED — private address outside listed range refused
```

---

## d20e72e — feat(tools): discover and import operations from an OpenAPI document

| Field | Value |
|---|---|
| check | 5 import tests in suite + 1 adversarial probe (unknown operation) |
| result | PASSED |
| rule | US1: fetch through egress (2MB limit); map operations via converter (all as writes); import re-reads source, takes method/path/inputs from document not caller; unknown operation refused; secret headers detected and templated |
| verdict | accept |
| defect | — |

12 files, 990 ins / 39 del. Key additions:

- **`modules/openapi.py`** (155 lines): `discover(spec, spec_url)` maps OpenAPI 3.0/3.1. `snake()`, `kebab()` for name normalization. `_deref()` (local $ref, 8-depth limit). `_field()` maps type/format/enum/example. `_secret_headers()` — apiKey in header becomes `{{NAME}}`, bearer becomes `Bearer {{NAME}}`. Every operation is marked write. multipart/form-data body skipped with warning.
- **`modules/service.py`**: `_fetch()` — GET through egress client, 2MB limit, 502 on upstream error. `_discover()` routes OpenAPI (fetch + parse JSON/YAML) vs MCP (raises at this commit). `discover()` returns public result without secret headers. `import_operations()` re-reads source (never trusts caller's method/path/inputs), refuses unknown ops, adds endpoint host to `module_egress_hosts`.
- **`modules/schemas.py`**: `DiscoveryResult`, `DiscoveredOperation`, `ModuleSourceIn`, `ImportOperationsIn`.
- **`modules/routes.py`**: Wired `discover` (POST) and `import_operations` (POST).
- **Tests** (`test_import.py`, 89 lines): 5 tests — discovery maps document as writes, unlisted host/HTTP refused (nothing fetched), non-document refused, import takes document not caller (forged method/path ignored), imported op needs secret before running.
- **`fixtures/openapi_bank.json`** (42 lines): OpenAPI 3.1 spec with 4 paths, apiKey security, $ref schema.
- **`fake_upstream.py`**: Added `/v1/openapi.json` and `/v1/not-a-spec` routes.

## d20e72e probe

### Probe 7: import naming an operation the document lacks — refused

Discovered 3 real operations: `get_account`, `place_hold`, `get_statements`. Tried importing `transfer_to_mars`.

```
import status: 400
error code: validation_failed
error message: transfer_to_mars is not in the source.
PROBE_7_RESULT: PASSED — unknown operation refused
```

---

## 1a0cd19 — feat(tools): import and call tools from an MCP server over streamable HTTP

| Field | Value |
|---|---|
| check | 5 MCP tests in suite (4 passed, 1 error unrelated) + 1 adversarial probe (no session id) |
| result | PASSED |
| rule | US2: MCP client over streamable HTTP; initialize → tools/list (paginated, 20-page cap) → tools/call; session id required; drift detection on re-import; mcp executor dispatches through egress |
| verdict | accept |
| defect | — |

8 files, 365 ins / 12 del. Key additions:

- **`mcp.py`** (160 lines): `McpSession` — `initialize()`, `list_tools()` (cursor pagination, 20-page cap), `call_tool()`. `_message()` parses JSON body or SSE `data:` lines. `_post()` handles notify (no id), session id tracking. `tool_output()` extracts structured or text content. `discovered()` maps MCP tools to `DiscoveryResult` (snake-case names, original name as `path`, all writes).
- **`executor.py`**: Added `McpExecutor` — checks egress, initializes session, calls `tools/call`, handles `EgressDenied` and `McpError`. `Executor` dispatches `"mcp"` executor type to it.
- **`modules/service.py`**: `_discover_mcp()` — egress check, initialize, list_tools, `mcp.discovered()`. Import sets `drift: true` when re-import finds previously-imported tool no longer listed by server. Sets `executor: "mcp"` on imported ops.
- **`fake_mcp.py`** (57 lines): Fake MCP server at `/v1/mcp`. Issues session id at initialize, requires it on all subsequent requests (returns JSON-RPC error -32000 without it). tools/list from mutable list (tests can mutate for drift). tools/call answers as SSE with structuredContent.
- **Tests** (`test_mcp.py`, 67 lines): 5 tests — discovery lists as writes, off-list refused (nothing contacted), imported tool runs through tools/call (structuredContent returned), drift on re-import (tool renamed), server refusing = 502.

## 1a0cd19 probe

### Probe 8: tools/call without session id — refused

```
no-session status: 200
no-session body: {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'no session'}}
PROBE_8a_RESULT: PASSED — tools/call without session id returns JSON-RPC error

wrong-session body: {'jsonrpc': '2.0', 'id': 2, 'error': {'code': -32000, 'message': 'no session'}}
PROBE_8b_RESULT: PASSED — wrong session id refused

session_id from initialize: sess-fake-1
with-session status: 200
PROBE_8c_RESULT: PASSED — with correct session id, tools/call succeeds (SSE)
```

---

Gate results on clean export of c6036f8:
- tools-service pytest: 50/50 PASSED (calls 9, egress 10, import 6, mcp 5, registry 5, secrets 6, modules api 9)
- `opa_server` module required from `ops_service_kit` but not present at this commit (added in 7d69b37); supplied from later commit to run tests. This is a broken-build-at-commit defect: conftest imports a module that doesn't exist yet.

## c6036f8 — feat(tools): AES-256-GCM secrets with tenant and name as authenticated data

| Field | Value |
|---|---|
| check | 50 tests in suite (6 new secrets tests) + 4 adversarial probes |
| result | PASSED |
| rule | US3: AES-256-GCM with context (tenant/name) as AAD — a value moved to another name or tenant fails to decrypt; OPS_SECRETS_KEY 64 hex, dev default refused outside dev; tool_secrets ciphertext only; secret_audit for create/rotate/delete/use; /v1/secrets never returns a value; {{NAME}} resolved on every call with no cache in both executors; every resolved value scrubbed from output and MCP error text; create-with-source re-reads the document like import |
| verdict | accept |
| defect | broken build at this exact commit: conftest.py imports `opa_server` from `ops_service_kit` but that module is only added in 7d69b37; tests cannot run standalone without it |

21 files, 1454 ins / 50 del. Key additions:

- **`secrets/cipher.py`** (49 lines): `AesGcmCipher` wrapping `cryptography`'s AES-256-GCM. `context_of(tenant_id, name)` produces the AAD string `"tenant/name"`. Encrypt generates a random 12-byte nonce; decrypt verifies tag + AAD. Blob format: base64 of nonce + ciphertext + tag.
- **`secrets/__init__.py`** (65 lines): `SecretResolver.headers()` finds `{{NAME}}` references in headers, calls `store.use()` to read+audit, decrypts via cipher, replaces references. Returns `(resolved_headers, used_values)`. `scrub(output, values)` replaces any plaintext value with `[secret]`.
- **`secrets/routes.py`** (103 lines): `/v1/secrets` CRUD. POST creates (name+value), POST `/{name}/rotate` rotates (new value, bumps version), DELETE `/{name}` removes, GET lists. **Never returns a value** — create returns name+version+createdBy+createdAt only.
- **`store/secrets.py`** (136 lines): `SecretStore` with `tool_secrets` (PK tenant_id+name, ciphertext, version, timestamps) and `secret_audit` (id, tenant_id, name, action, version, actor, tool, at). `use()` reads ciphertext+version, updates `last_used_at`, writes audit row — all in one transaction.
- **`executor.py`** changes: `_Secrets` mixin shared by `HttpExecutor` and `McpExecutor`. `_resolve()` calls `SecretResolver.headers()`, returns `(headers, used_values)` or a `ToolOutcome` on `SECRET_MISSING`. Both executors call `scrub()` on output and MCP error text.
- **`modules/service.py`** changes: `_chosen()` static method extracted. Create (POST module) accepts `source` field and re-reads the document like import — forged method/path/headers from caller are overwritten by the source.
- **Migration `0005_secrets.py`**: creates `tool_secrets` and `secret_audit` tables.
- **`test_secrets.py`** (167 lines, 6 tests): value never returned, rotation reaches next call, no value in response/log/error/logline (scrub of echo-headers upstream), missing/misplaced secret sends nothing, every action audited, dev key refused outside dev.
- **`conftest.py`** changes: per-session OPA via `opa_server.session_url()` (fixing shared-OPA state issue). `build_app` wires cipher, SecretStore, secrets_router, SecretResolver.

## c6036f8 probes

### Probe 9: secret value never returned by any route

```
create response keys: ['name', 'version', 'createdBy', 'createdAt']
PROBE 9a: value absent from create response
PROBE 9b: value absent from list response
PROBE 9c: value absent from call response
PROBE 9d: upstream received real value, confirming it was sent but not leaked
PROBE_9_RESULT: PASSED — secret value never returned by any route
```

### Probe 10: moved ciphertext fails to decrypt (AAD mismatch)

```
same context: decrypts OK
PROBE_10a: wrong name fails to decrypt (AAD mismatch)
PROBE_10b: wrong tenant fails to decrypt (AAD mismatch)
PROBE_10_RESULT: PASSED — moved ciphertext fails to decrypt
```

### Probe 11: upstream echoes secret header — scrubbed from response

```
upstream received x-api-key: sk-echo-probe-value-xyz
PROBE_11_RESULT: PASSED — secret sent to upstream, scrubbed from response
```

### Probe 12: secret value not in test output

```
PROBE_12_RESULT: PASSED — secret value not in test output
```

---

Gate results on clean export of 3750893:
- tools-service pytest: 50/50 PASSED

## 3750893 — fix(tools): a drifted module runs no calls until it is reviewed again

| Field | Value |
|---|---|
| check | 50 tests in suite (drift test expanded) + 1 adversarial probe |
| result | PASSED |
| rule | T006: a re-import that drops a tool flags the module drifted; the executor refuses all operations on a drifted module until the approval is renewed |
| verdict | accept |
| defect | — |

2 files, 10 ins / 3 del. Changes:

- **`app.py`** (+3 lines): `_before_policy` gains a new check: if `module["drift"]` is true, returns 403 `module_drifted` with message naming the module. Runs before OPA, before anything leaves the gateway.
- **`test_mcp.py`** (+3 lines): existing drift test expanded — after re-import that drops a tool, `gateway_call("find_case", ...)` asserts `status_code == 403` and `error.code == "module_drifted"`.

## 3750893 probe

### Probe 13: drift blocks calls, re-approval unblocks

```
step 1: imported lookup_case, drift=False
step 2: pre-drift call status=200
step 3: re-imported find_case (lookup_case gone), drift=True
step 4: drifted call status=403, code=module_drifted
PROBE_13a: PASSED — surviving operation refused with module_drifted
step 5: post-approve call status=200
PROBE_13b: PASSED — call succeeds after re-approval
PROBE_13_RESULT: PASSED — drift blocks calls, re-approval unblocks
```

---

## 1a0cd19 MCP error investigation

Proto-orch hold: "test_an_mcp_server_off_the_allow_list_is_never_contacted" errored in the initial full-suite run but was not reproducible.

Test name: `test_an_mcp_server_off_the_allow_list_is_never_contacted` (test_mcp.py line 33)
Assertion: `assert r.status_code == 502 and r.json()["data"]["output"]["error"]["code"] == "EGRESS_DENIED"`

Re-run alone: 1/1 PASSED.
Re-run full suite: 44/44 PASSED.

Root cause: the initial run happened before the egress migration (0004) was applied to the shared test database. The `egress_hosts` table didn't exist, causing a ProgrammingError that surfaced as an error (not a test failure). After `alembic upgrade head`, the test passes reliably alone and in the full suite. This is a test-environment setup issue, not a code defect.

---

Gate results on clean export of 3cbf54a:
- tools-service pytest: 51/51 PASSED (calls 9, egress 10, import 6, mcp 5, registry 5, secrets 6, modules api 10)
- uc-012 (tool import + review workflow): 11/11 PASSED
- uc-013 (secrets lifecycle): 7/7 PASSED

## 3cbf54a — feat(tools): real https fake bank, uc-012/013, review decide route

| Field | Value |
|---|---|
| check | 51 tests in suite + uc-012 (11) + uc-013 (7) + 2 adversarial probes |
| result | PASSED |
| rule | T007: dev-only egress_resolve (OverrideResolver) refused outside dev; egress_ca_file for internal CAs; review decide route — never the requester (403), changes_requested needs findings; approval publishes and clears drift; per-session OPA in tests fixes shared-state flake |
| verdict | accept |
| defect | — |

28 files, 1099 ins / 14 del. Key additions:

- **`egress.py`** changes: `OverrideResolver` — dev-only DNS override with port remapping. `egress_client()` accepts `ca_file` for internal CA bundles.
- **`settings.py`** changes: `egress_ca_file: Path | None` and `egress_resolve: dict[str, str]` with validator: `egress_resolve` raises `ValueError("egress_resolve is for dev only; outside dev, names resolve through DNS")` when `environment != "dev"`.
- **`modules/service.py`** (+40 lines): `decide_review()` — validates requester is not decider (403 "You requested this review. Someone in Security must decide it."), `changes_requested` without findings raises `ValidationFailed`, approval publishes module and clears drift.
- **`modules/routes.py`**: `POST /{module_id}/reviews/{review_id}/decide` wired.
- **`modules/schemas.py`**: `ReviewDecisionIn` — `decision: Literal["approved", "changes_requested"]`, `findings: list[str]`, `note: str | None`.
- **`opa_server.py`** (73 lines): per-session OPA Docker container on a free port, fixing the shared-OPA state corruption seen in earlier runs.
- **`fake_bank_https.py`** (184 lines): HTTPS fake bank with self-signed cert on private address, serving OpenAPI spec + MCP server.
- **uc-012** (94 lines, 11 checks): egress refusal, discovery, import (document not caller), review+publish, call, MCP, drift.
- **uc-013** (70 lines, 7 checks): secret missing refuses, create never returns value, call carries secret, echo scrubbed, rotation works, executions log clean, delete works.
- **`test_tool_modules_api.py`** (+1 test): `test_security_decides_a_review_never_its_requester_and_approval_publishes` — requester gets 403, different user can decide, changes_requested without findings refused, approval publishes.

## 3cbf54a probes

### Probe 14: egress_resolve with environment=production — refused at startup

Set `OPS_ENVIRONMENT=production`, `OPS_AUTH_MODE=platform`, real review_key/service_token/secrets_key, and `OPS_EGRESS_RESOLVE='{"bank.test": "127.0.0.1:9999"}'`. Settings construction raised:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
  Value error, egress_resolve is for dev only; outside dev, names resolve through DNS
PROBE_14_RESULT: PASSED — service refuses to start with egress_resolve outside dev
```

### Probe 15: requester cannot decide their own review (403)

Created an operation, requested a review (caller = requester), then tried to decide it as the same user:

```
step 1: operation added
step 2: review requested, id=rev_df18827a1fcc
step 3: self-decide status=403, body={"success":false,"error":{"code":"forbidden","message":"You requested this review. Someone in Security must decide it.",...}}
PROBE_15_RESULT: PASSED — requester cannot decide their own review
```

---

## Triage

Seven commits reviewed, fifteen adversarial probes run. One minor defect noted.

| Entry | Finding | Verdict |
|---|---|---|
| 6132606 tenant egress allow-list | accept, no defect | — |
| 642aa65 egress policy resolve-once-and-dial | accept, no defect | — |
| d20e72e OpenAPI discovery and import | accept, no defect | — |
| 1a0cd19 MCP client over streamable HTTP | accept, no defect (MCP error = test env setup, not code) | — |
| c6036f8 AES-256-GCM secrets | accept, minor: broken build at commit (opa_server import precedes its addition) | — |
| 3750893 drifted modules block calls | accept, no defect | — |
| 3cbf54a real https fake bank + uc-012/013 + review decide | accept, no defect | — |
| Probe 1: public range → 400 | refused, loopback and link-local also refused | — |
| Probe 2: unlisted host → 422 | naming the host, code `egress_host_not_allowed` | — |
| Probe 3: remove used host → 409 | naming the module that uses it | — |
| Probe 4: migration up/down/up | data preserved at every step | — |
| Probe 5: public+private resolver → refused | all addresses checked, private outside range caught | — |
| Probe 6: private outside listed range → refused | 10.0.0.5 not in 172.16/12 | — |
| Probe 7: unknown operation import → 400 | "transfer_to_mars is not in the source." | — |
| Probe 8: MCP no session → error | JSON-RPC -32000; wrong session also refused; correct session works | — |
| Probe 9: secret never returned | value absent from create, list, call response; upstream received it | — |
| Probe 10: moved ciphertext → AAD mismatch | wrong name and wrong tenant both fail to decrypt | — |
| Probe 11: echo header scrubbed | upstream received real value; response scrubbed | — |
| Probe 12: secret not in log | value absent from test stdout/stderr | — |
| Probe 13: drift blocks, reapprove unblocks | 403 module_drifted; clear drift → 200 | — |
| Probe 14: egress_resolve in production → ValueError | service refuses to start | — |
| Probe 15: self-decide review → 403 | "You requested this review. Someone in Security must decide it." | — |

## 71a9e34 — docs(tools): update overview with egress, import, MCP, secrets, review decide

| Field | Value |
|---|---|
| check | diff read, claims verified against reviewed code |
| result | PASSED |
| rule | documentation must accurately reflect shipped code |
| verdict | accept |
| defect | — |

1 file, 17 ins / 7 del. Updates `docs/services/tools-service/overview.md`:

- Tests description: adds egress, import, MCP, secrets, fake bank + MCP server. Accurate.
- Registry row: adds `POST .../reviews/{id}/decide`, approval publishes. Accurate per 3cbf54a.
- New Egress row: allow-list, https/443, resolve-once-and-dial, no proxies/redirects. Accurate per 642aa65.
- New Import row: OpenAPI 3.0/3.1 + MCP streamable HTTP, drift on re-import. Accurate per d20e72e/1a0cd19.
- New Secrets row: AES-256-GCM, tenant+name bound, never returned, scrubbed. Accurate per c6036f8.
- Executors updated: `{{NAME}}` headers from secrets, `mcp` executor. Accurate.
- Decisions: egress inside connection (not before), private ranges listed, imported ops are writes, secrets bound+scrubbed. All match code and test evidence.
- "Not yet": removes discovery/import/secrets (shipped), adds fileId upload, MCP stdio, KMS, roles, console gaps.
- Use cases: adds uc-012/013 with private-network note. Settings: adds OPS_SECRETS_KEY, OPS_EGRESS_CA_FILE, OPS_EGRESS_RESOLVE.

No adversarial probes — documentation only, all claims verified against the seven code commits already reviewed.

---

## Final triage

Eight commits reviewed, fifteen adversarial probes run. One minor defect noted.

| Entry | Finding |
|---|---|
| 6132606 tenant egress allow-list | accept |
| 642aa65 egress policy resolve-once-and-dial | accept |
| d20e72e OpenAPI discovery and import | accept |
| 1a0cd19 MCP client over streamable HTTP | accept |
| c6036f8 AES-256-GCM secrets | accept, minor: broken build at commit (opa_server import precedes its addition) |
| 3750893 drifted modules block calls | accept |
| 3cbf54a real https fake bank + uc-012/013 + review decide | accept |
| 71a9e34 overview doc update | accept |

verdict: approve
