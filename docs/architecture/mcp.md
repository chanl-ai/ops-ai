# MCP in Ops AI

Status: current design. Each row says whether it is built or not built yet.

Ops AI speaks the Model Context Protocol in two directions. Outside assistants such as Claude, Cursor and ChatGPT
reach a team's tools at one address, and Ops AI calls outside MCP servers as governed tools for its agents and
workflows. Every call in both directions goes through the same gateway, so it meets the same approvals, limits,
masking and audit as any other tool call.

Read with [tool lifecycle](tool-lifecycle.md), [workflows as tools](workflows-as-tools.md), the
[MCP server design](../design/tools/mcp-server.md) and the [service map](service-map.md). Code is cited at
`origin/develop` `4b7e6a49`; `T/` below means `services/tools-service/src/ops_tools/`.

## Scope

| In | Out | Later |
|---|---|---|
| Ops AI as an MCP server per team and per person; Ops AI as an MCP client; agents and workflows using MCP tools; knowledge, skills and a guide served as tools; an admin and builder module; sign-in, audit, rate limits and masking | A stdio transport (the gateway never starts a process); anonymous or guest access; installing plugins from a chat | The MCP Tasks extension for held writes; production access for outside assistants |

## Status by angle

| Angle | Built | Where | Not built yet |
|---|---|---|---|
| Server per team | `/mcp/{team}` behind the `mcp_gateway` flag; read tools only; every call a test run | `T/mcp_server.py:39`, `:101-114`, `:118-125`; `T/app.py:259-298`; `packages/ops_service_kit/src/ops_service_kit/flags.py:29-31` | `/mcp/{env}/{team}`; curated endpoints `/mcp/{env}/{team}/e/{slug}`; server instructions; Origin check |
| Server per person | A person's token is accepted on the team address | `packages/ops_identity/src/ops_identity/resolve.py:116-130` | A way for a client to get that token (the sign-in server below); the audience check |
| Client of outside servers | An outside server is a module of type `mcp`; `initialize`, paged `tools/list`, `tools/call` over streamable HTTP on the egress allow-list; tools pinned and refused on drift | `T/mcp.py:72-143`; `T/executor.py:578-681`, `:775`; `T/modules/schemas.py:18`; `T/modules/routes.py:131`; `T/apps.py:2098` | Nothing |
| Agents and workflows | Agents and workflow steps call MCP-backed tools through `POST /v1/calls`; tool search above 20 tools | `services/agents-service/src/ops_agents/activities/gateway.py:242`; `packages/ops_agent_kernel/src/ops_agent_kernel/types.py:74` | Nothing |
| Knowledge, skills, guide | The team's skills the caller may read are prompts named by slug, their inputs as arguments; `prompts/list` and `prompts/get` are gateway reads named by those methods. A knowledge base carries an `access.mcp` switch that is always off | `T/mcp_tools.py` (`prompts`, `prompt`); `T/mcp_server.py` (`_list_prompts`, `_get_prompt`); `services/kb-service/src/ops_kb/service.py:420` | `search_knowledge`; `search_skills`, `get_skill`, `save_skill`; `guide` |
| Admin and builder | `list_templates` and `install_template`, public API operations offered as tools beside the team's own, each a gateway call; the SDKs and the `opsai` CLI cover the rest | `T/mcp_tools.py` (`OPERATIONS`); `sdk/python/src/ops_ai/`, `sdk/typescript/src/` | The rest of the public API as tools |
| Sign-in | Inbound: API key `Bearer ok_…`. Outbound: RFC 9728 metadata, RFC 8414 issuer match, PKCE S256, RFC 8707 resource, optional dynamic registration | `resolve.py:125-126`; `T/auth/discovery.py:1-9`, `:80-141`; `T/auth/tokens.py:379` | An OAuth 2.1 server in platform-service; protected resource metadata; a 401 that points at it |
| Audit, limits, masking | One `gateway_calls` row per call with `channel` and `client_name` (`T/store/calls.py:65-67`); a per-operation rate window in PostgreSQL (`T/store/rate_windows.py:1-6`, spent at `T/gateway_calls.py:354-364`); output masks and secret scrub (`T/executor.py:106`, `:539`) | As cited in the cell | A rate window per token; personal data masked per endpoint |

## One owner per job

There is one MCP server and one MCP client, both in tools-service, and one token issuer, platform-service.

| Job | Owner | Where |
|---|---|---|
| Serve MCP to outside assistants | tools-service `McpAdapter` | `T/mcp_server.py:51`; mounted at `T/app.py:294-298` |
| Call outside MCP servers | tools-service `McpExecutor`, `McpSession` | `T/executor.py:578`; `T/mcp.py:72` |
| Decide and run every call | `GatewayCalls.call` | `T/gateway_calls.py:288` |
| Issue tokens | platform-service | `services/platform-service/src/ops_platform/api/app.py:310` (signing keys today) |
| Verify the caller | `ops_identity` `bearer` | `resolve.py:116` |
| Who may run what | `ops_access.can` and the roles grid | `packages/ops_access/src/ops_access/check.py:53-60` |
| Which account a call uses | `PluginHost.for_call` | `T/plugins/host.py:916` |
| Curated endpoints | tools-service (not built yet) | — |
| Long-lived keys on an endpoint | platform-service mints an API key bound to one endpoint; tools-service stores the binding (not built yet) | — |
| Knowledge search for assistants | kb-service search, reached as a tool through the gateway (not built yet) | — |
| Skill records | agents-service `/v1/skills` | `services/agents-service/src/ops_agents/api/routers/skills.py:1` |
| Held writes | agents-service Reviews, through a system workflow started by a service event | `T/modules/review_events.py:17` (the same seam tool access requests use) |
| Audit | `gateway_calls` | `T/store/calls.py:65-67` |

Two places named MCP outside tools-service. Neither serves MCP, and each becomes a pointer at a curated endpoint:
the agents-service deployment channel `mcp` (`services/agents-service/src/ops_agents/api/routers/channels.py:42`,
gallery kind off at `channel_list.py:48`) and the knowledge base's `access.mcp` switch (`service.py:420`). The
console's MCP page (`apps/console/src/app/channels/mcp/page.tsx`) reads `/connect` routes
(`apps/console/src/lib/api/connect-http.ts:9-12`) that no service serves yet; only the mock answers them.

## Behaviour

| Rule | Built |
|---|---|
| An MCP call is one gateway call: the registry decides the access class, then schema, limits, OPA, the rate window, the executor and the call log | Built (`T/gateway_calls.py:1-6`, `T/mcp_server.py:116-140`) |
| The caller comes only from the verified key or token, never from a header or a body | Built (`T/mcp_server.py:80-83`) |
| A key or token for another team gets 403 `team_forbidden` | Built (`resolve.py:116-120`) |
| A service token on the MCP address is refused | Built (`resolve.py:127-128`) |
| The tool list is filtered by the caller's rights and the team's visibility; an unknown team sees nothing | Built (`T/mcp_server.py:87-99`) |
| The title is always set; every listed team tool is a read, so its `readOnlyHint` is true; `install_template` is the one listed write | Built (`T/mcp_server.py` `_list_tools`, `T/mcp_tools.py` `tools`) |
| `readOnlyHint` and `destructiveHint` come per tool from the access class and the approval policy | Not built yet |
| Every outside-assistant call is a test run, using an app's sandbox account when the team has one | Built (`T/mcp_server.py:121-125`) |
| A write without an approval is refused | Built (`T/gateway_calls.py:405-438`) |
| A write from a signed-in person is held: a pending result with a review link that expires after 24 hours; an approver other than the requester decides in Reviews; it runs once as the requester; `get_call` reads the outcome | Not built yet |
| An API key runs reads only; a write answers 403 `insufficient_scope` | Reads only built (`check.py:53-60`); the 403 code not built yet |
| Above 20 tools an endpoint serves `search_tools`, `get_tool`, `run_tool` over the same set; an empty set denies all | Not built yet (the threshold is `types.py:74`) |
| The model never picks the account; the endpoint's account map does | Built for agents (`T/plugins/host.py:916`); endpoints not built yet |
| A token works only on the exact address it was issued for, and a test token never reaches production | Not built yet |
| With no issuer configured, the MCP address answers 503 with the reason; keys keep working | Not built yet |
| A client registers by a pre-registered record or a client ID metadata document; dynamic registration is off | Not built yet |
| Personal data is masked in what an MCP client receives unless a team manager turns it off, and that change is audited | Not built yet |
| Knowledge is served as a search tool through the gateway, never as MCP resources, so each read is limited and audited | Not built yet |
| A skill read with `prompts/list` or `prompts/get` is a gateway read named by that method, so it is limited and audited like a tool call; a person who may not read skills gets no prompts | Built (`T/mcp_server.py` `_platform_call`) |
| A platform operation (`list_templates`, `install_template`) is a gateway call: one `gateway_calls` row on the `mcp` channel, a rate window per tenant, and `install_template` is a write that waits for a person unless the caller is their own approver | Built (`T/gateway_calls.py` `call(operation=…)`, `T/mcp_tools.py` `resolved`) |
| Running any tool, a platform operation included, needs `tools:run`; a member without it gets a tool error | Built (`T/mcp_server.py` `_call_tool`) |
| A platform operation's service token carries only the cells the person holds in the team, and the owning service decides with its own `can` (no `skills:create`, no skill installed) | Built (`T/mcp_tools.py` `_headers`) |
| A write a platform operation makes names the person as its maker, through an acting-for token platform-service signs | Built (`T/mcp_tools.py` `_acting_for`) |
| A skill saved from a chat is a draft that a builder publishes | Not built yet |
| An outside server's tools are pinned by schema; a changed tool is refused until re-imported and reviewed | Built (`T/modules/service.py:456`) |
| Every request to an outside server goes through the egress allow-list at a checked address | Built (`T/mcp.py:1-8`, `:100-107`) |

## Data

| Record | Service | Fields | Built |
|---|---|---|---|
| `gateway_calls` | tools | adds nothing; `channel` is `api`, `mcp` or `console`, with `client_name` | Built (`T/store/calls.py:65-67`) |
| `mcp_endpoints` | tools | `id`, `team_id`, `slug`, `environment`, `tool_names`, `accounts`, `who`, `masked`, `paused` | Not built yet |
| `mcp_endpoint_keys` | tools | `endpoint_id`, `key_id` (a platform-service key), `person_id` | Not built yet |
| OAuth clients, codes, refresh tokens | platform | client id, redirect addresses, metadata document address; codes bound to PKCE and resource | Not built yet |

## API

The MCP mount stays out of OpenAPI. Every other route is generated into the SDKs.

| Route | Who | Service | Built |
|---|---|---|---|
| `POST /mcp/{team}` | A key or token in the team opens a session and lists; each tool call needs `tools:run`, and each prompt read needs `skills:view` | tools | Built |
| `POST /mcp/{env}/{team}`, `/mcp/{env}/{team}/e/{slug}` | Same | tools | Not built yet |
| `GET /.well-known/oauth-protected-resource/mcp/{env}/{team}[/e/{slug}]` | Anyone | tools | Not built yet |
| `GET /.well-known/oauth-authorization-server`, `/oauth/authorize`, `/oauth/token`, `/oauth/revoke` | Clients and people | platform | Not built yet |
| `GET`, `POST /v1/mcp-endpoints`; `/{id}`, `/{id}/pause`, `/{id}/keys`, `/{id}/calls` | `tools.run` for one's own key; `connections.manage` to curate, pause, unmask | tools | Not built yet |
| `POST /v1/tool-modules/discover` with `{kind: "mcp", url}` | `tools.create` | tools | Built (`T/modules/routes.py:131`) |

## Security, audit and evidence

| Concern | Rule |
|---|---|
| Identity | From the verified key or token only (`resolve.py:116`) |
| Approvals | Bound to the input hash, counted by OPA, decided in Reviews (`T/gateway_calls.py:449-469`; `services/tools-service/policy/gateway.rego:23-65`) |
| Tokens upstream | An inbound token never reaches an outside system; the gateway holds its own token per account (`T/auth/tokens.py:379`) |
| Audit | One row per call in `gateway_calls`, with the channel and the client's claimed name shown as a claim |
| Masking | Output paths and secrets are scrubbed before an answer is returned or logged (`T/executor.py:106`, `:539`) |

## Acceptance tests

| Test | Can fail by |
|---|---|
| A key lists a team's read tools and runs one; one `gateway_calls` row has `channel = mcp` | The adapter not entering the team's data scope |
| An unsigned request gets 401 with `resource_metadata` naming platform-service | A 401 with a realm only |
| A token for one team or endpoint is refused on another, and a test token on production | Dropping the audience check |
| A key's write gets 403 `insufficient_scope` and no hold | Letting a key open a hold |
| `search_tools` on an endpoint of 25 tools returns only those tools | Searching the whole team |
| A held write runs once as the requester after another person approves, and never after 24 hours | Accepting the requester as approver |
| An imported MCP tool whose schema changed is refused | Skipping the drift check |

## Open questions

None. Questions about an unbuilt slice are raised on that slice's work item.
