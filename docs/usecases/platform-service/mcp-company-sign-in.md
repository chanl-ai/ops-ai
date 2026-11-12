# A person connects an assistant to a team's MCP address with their company sign-in

Status: draft. Id: `uc-733`. Service: `platform-service`. Layers: api, ui.

A person pastes a team's MCP address (`<public URL>/mcp/<team>`) into Claude, Cursor, VS Code or ChatGPT. The assistant
finds platform-service as the authorization server from the 401, registers itself, and sends the person to the console's
consent page. After the person signs in (password or OIDC first; a SAML group once the company-sign-in change is merged,
which is the only reason step 6's SAML variant waits) and presses Allow, the assistant holds a 15-minute token for that
one address and a renewal that lasts the workspace's connection length (default 8 hours, at most 30 days).

Contract the tests fix: `GET /.well-known/oauth-authorization-server`; `POST /oauth/register`; `GET /oauth/authorize`
(redirects the browser to the console's `/oauth/authorize` page, or answers 400 with no redirect); `GET` and `POST
/v1/oauth/consent` with the person's console sign-in; `POST /oauth/token`; `GET /v1/oauth/grants` and `DELETE
/v1/oauth/grants/{id}`; policy `mcpConnectionHours`; token claims `aud` (the address only), `team_ids`, `client_id`; call log
column `client_id`; table `oauth_clients` (`id`, `created_at`); registration limited to 10 a minute per source address, clients never consented to pruned after 24 hours by the next registration, at most 500 clients per tenant; the registration audit row has no tenant and gains tenant and team at the first consent. tools-service answers `/.well-known/oauth-protected-resource/mcp/<team>` and verifies only through
`ops_identity` with the address as the expected resource.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A client with no token finds where to sign in, or is told the install names no issuer | api | 1 | 1 |
| S2 | The person signs in, allows, and the assistant lists their tools; a console token and a token for another address are refused at the MCP address | api | 2-4 | 4 |
| S3 | A person who leaves the team cannot renew | api | 5 | 5 |
| S4 | The consent page shows the real redirect host and the client's name as self-reported, cannot be framed, and holds in every state at both widths | ui | 6-8 | 8 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Free use-case ports | the runner picks them and its own database |
| The install's public URL | `OPS_PLATFORM_PUBLIC_URL` on platform-service and tools-service, the address the assistant pastes |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | No token at `/mcp/team_ops`; read the metadata it names; read the server metadata | 401 with `resource_metadata`; metadata names platform-service; `code_challenge_methods_supported` is `["S256"]` |
| 2 | A scripted client registers, James (builder) allows, the client exchanges the code with its PKCE verifier | 200, `aud` is the address only, `team_ids` is `["team_ops"]` |
| 3 | `tools/list` at `/mcp/team_ops` with that token | 200 |
| 4 | The same request with James's console token, and with the token at another team's address | 401, 401 |
| 5 | Priya removes James from team_ops; the client renews | 400 `invalid_grant` |
| 6 | The consent page for a client named "Official Microsoft Copilot" with a redirect to `https://claude.example/callback` | Shows `claude.example`, the name marked as the name the client gave itself, the team and the tool count |
| 7 | The consent page response headers | `frame-ancestors 'none'` |
| 8 | The consent page and My security > Connected assistants as an admin and a member at 1440 and 390 with `?mock=empty`, `slow`, `error` | Match the mock; nothing clipped |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-733-api.py` | failing |
| ui | `platform-service/scripts/test-uc-733-ui.mjs` | failing |

Steps that wait: a SAML group giving the team (`uc-mcp-2` with SAML) and a company that requires its sign-in showing no
password form (`uc-mcp-16`) need the company-sign-in change that is not merged yet.

## Non-vacuous check

`a console token is refused at the MCP address`: with the audience check removed, step 4's console token lists tools and
the check fails.
