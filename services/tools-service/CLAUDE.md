# tools-service: working rules

Status: current.

The tools service (`ops_tools`, :8720) is the only way a tool call leaves the platform. It owns the tool-module
registry behind the console's Tools pages, apps and their accounts (how the platform signs in to a system), secrets,
the egress allow-list, mailboxes, plugins, mocks, code-tool runs (sent to runner-service) and the call log. Every
call is decided by OPA (`policy/gateway.rego`): a write runs only with an approval token bound to the sha256 of its
canonical input and the run's lease generation. It also serves the MCP endpoint (`mcp_server.py`).

Its one model use, the check before sending (`send_check.py`), goes through models-service with its own model key;
it never holds a provider credential. It does not decide what an agent may hold: agents-service grants, and this
service checks the grant on each call. Shared service rules: [services/CLAUDE.md](../CLAUDE.md). Cross-folder
rules: [root guide](../../CLAUDE.md#folder-guides).

## Code

| Path | Holds |
|---|---|
| `src/ops_tools/__main__.py` | Start: settings, stores, OPA policy and review key written to OPA, plugin loading, `create_gateway_app` |
| `src/ops_tools/app.py` | The gateway app: `POST /v1/calls` (`:418`) and the routers mounted on it |
| `src/ops_tools/opa.py` | The OPA client and the decision input |
| `src/ops_tools/modules/` | Tool modules: registry routes, versions, security reviews, workflow approvals, OpenAPI import, the call log (`/v1/executions`, `routes.py:59`) |
| `src/ops_tools/connections/`, `auth/` | App accounts, sign-in kinds, OAuth with PKCE, keep-alive |
| `src/ops_tools/secrets/`, `store/secrets.py` | Secrets: written once, never returned, scrubbed from upstream answers |
| `src/ops_tools/plugins/` | Loads every plugin in `OPS_PLUGINS_DIR` (the repo's `plugins/` locally) and runs its tools; apps, templates and knowledge sources from plugins |
| `src/ops_tools/egress.py`, `egress_routes.py`, `held_hosts.py` | The allow-list; https on 443 to a listed host, address checked at connect |
| `src/ops_tools/executor.py`, `code_runs.py`, `mcp.py` | HTTP operations, code tools on runner-service, MCP upstreams |
| `src/ops_tools/store/` | All database code; `store/connections.py:41` names the tenant role `ops_tools_tenant` |
| `policy/` | `gateway.rego` and `data.json`, loaded into OPA at start |
| `seed/tool_modules.json` | The dev registry, loaded in dev |
| `scripts/fake_bank/` | The fake bank (`api.bank.test`) that `make up` runs as `fakebank` |
| `migrations/` | Its own chain, version table `alembic_version_tools` |
| `tests/` | Registry, routes, egress, import, MCP, secrets, plugins, against an in-process fake bank and MCP server; `fixtures/` |

## Run, test, lint

From this folder (`make help` lists every target):

| Task | Command |
|---|---|
| Serve in the foreground on :8720 | `make stop`, then `make run` |
| One test file | `make test T=tests/test_cors.py`, or from the root `make test PKG=services/tools-service T=tests/test_cors.py` |
| All of its tests | `make test` (starts compose first) |
| The gateway tests, which live in agents-service | `make test-gateway` |
| Lint, types, OpenAPI | `make lint`, `make typecheck`, `make openapi-check` (`make openapi` to regenerate) |
| Everything but the tests | `make checks` |
| Apply the chain | `make migrate` |
| Background process | `make logs FOLLOW=0`, `make health` |

Tests that need OPA start a private OPA container on a free port (`ops_service_kit.opa_server`, used in
`tests/conftest.py`); only the live stack uses :8181, because every tools-service start rewrites the review key and
policy in the OPA it is given.

## Try it as a person

```bash
make api GET /v1/apps AS=builder SVC=tools
make api GET /v1/executions AS=builder SVC=tools Q='pageSize=5'   # the call log
make api GET /v1/egress/hosts AS=security SVC=tools
make chat-calls THREAD=th_… AS=james                              # one chat thread's tool calls
```

Reference: [make/CLAUDE.md](../../make/CLAUDE.md).

## Rules for this service

| Rule | Detail |
|---|---|
| One egress | Every outbound request, discovery included, is https on 443 to an allow-listed host, resolved once and connected to the checked address; no proxies, no redirects |
| Writes need a token | OPA refuses a write without an approval token for exactly this input; a test for a new write path pairs the refusal with the success |
| Secrets | Written once from a person's request, never read back through any route, scrubbed from upstream answers, every use audited |
| Accounts | An account's credentials go only to the scheme, host and port of its `baseUrl` (`CONNECTION_HOST_MISMATCH` otherwise) |
| Plugins | A plugin that fails to load is logged with the reason and the others still load (`plugins/host.py`, `tests/test_plugin_load_failure.py`). There is no `GET /v1/plugins` route, although `plugins/README.md` and [docs/guide/plugins.md](../../docs/guide/plugins.md) name one |

## Known departures

- `ops_tools` imports `ops_agents.activities` (`registry.py:14`, `tools.py:11`, `__main__.py:16`) for the seed
  catalogue and local executors, so this service does not yet stand alone.
- The gateway's tests are in `../agents-service/tests/gateway` until that import is gone.

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/tools-service/overview.md](../../docs/services/tools-service/overview.md) | What is built: registry, egress, import, secrets, accounts |
| [docs/services/tools-service/design.md](../../docs/services/tools-service/design.md) | Design |
| [docs/design/tools/tool-system.md](../../docs/design/tools/tool-system.md), [mcp-server.md](../../docs/design/tools/mcp-server.md) | Proposed extensions |
| [docs/architecture/tool-lifecycle.md](../../docs/architecture/tool-lifecycle.md) | A tool from import to call |
| [docs/usecases/tools-service/](../../docs/usecases/README.md) | 39 use cases |
| [openapi.json](openapi.json) | The API; `openapi-untyped.txt` lists the untyped operations still allowed |
