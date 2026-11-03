# An install turns a feature on or off from its config

Status: passing. Id: `uc-612`. Service: `tools-service`. Layers: api, ui.

An install lists the features it turns on in `OPS_FLAGS` (`ops-ai.env`); every flag in the registry
(`packages/ops_service_kit/src/ops_service_kit/flags.py`) is off until named. The first flag, `mcp_gateway`, hides the
address outside assistants use to reach a team's tools: tools-service answers `/mcp` with 404 `feature_off`, and the
console offers nothing about it. Install docs: `docs/deploy/install.md`, "Feature flags".

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An operator misspells a flag in the install config, and each service refuses to start, naming it | api | 1 | 1 |
| S2 | On an install with no flags, an outside assistant opening the MCP address is told it is off, and the console's answer lists every flag off | api | 2 | 2 |
| S3 | On an install that names `mcp_gateway`, the MCP address serves and the console's answer says it is on | api | 3 | 3 |
| S4 | A person on an install with no flags finds nothing offering the MCP address or connecting an assistant | ui | 1 | 1 |
| S5 | A person on an install that turns `mcp_gateway` on finds the MCP channel, its ⌘K entries and the Tools link | ui | 2 | 2 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| platform-service and tools-service on the use-case database, platform sign-in | the harness's `platform()` and `tools()`; the ui layer's `withUiStack({ platform: true, tools: {} })` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 (api) | tools-service and platform-service start with `OPS_FLAGS=mcp_gatway` | Each exits at start with "unknown flag mcp_gatway in OPS_FLAGS; known flags: …" |
| 2 (api) | Both start with `OPS_FLAGS` empty; Priya reads `GET /v1/me`; an anonymous caller posts `tools/list` to `/mcp/test/team_ops` | `flags` lists `mcp_gateway` and every flag off; `/mcp` is 404 `feature_off` |
| 3 (api) | Both start with `OPS_FLAGS=mcp_gateway`; the same reads | `mcp_gateway` is on; `/mcp` is 401 `unauthorized` (the adapter serves and asks for sign-in). uc-410 lists and refuses with the flag on |
| 1 (ui) | No flags: Priya opens ⌘K and searches "mcp", opens Channels and its Connect channel menu, `/channels/mcp`, and Tools › Workflows | No "Connect your assistant" or "Copy MCP URL"; no MCP tab or card; the menu says "Slack and Teams are coming soon"; `/channels/mcp` is not found; no "Manage exposure on the MCP tab" |
| 2 (ui) | `OPS_FLAGS=mcp_gateway`: the same walk | Both ⌘K entries, the MCP tab and card, the MCP channel page and the Tools link show |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-612-api.py` | passing, `make usecase-test UC=uc-612 LAYER=api` (2026-11-01, 9 checks) |
| ui | `tools-service/scripts/test-uc-612-ui.mjs` | passing, `make usecase-test UC=uc-612 LAYER=ui` (2026-11-01, 13 checks) |

## Non-vacuous check

Step 2's `/mcp` check is the off path: `services/tools-service/tests/test_mcp_server.py` failed its listing test with
Not Found when the default turned the adapter off and the test did not yet set the flag, and
`test_with_the_flag_off_the_mcp_address_says_it_is_off` asserts the `feature_off` code and message. Step 1 fails when
`Settings._known_flags` does not check: `packages/ops_service_kit/tests/test_flags.py` reported "DID NOT RAISE" with the
check removed. The console's rule 19 in `apps/console/scripts/check-standards.mjs` reported
`workflow-tools-table.tsx:65` once the file stopped reading `mcp_gateway`.
