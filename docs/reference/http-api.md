# HTTP API

Status: current. The route pages in this tab are generated from each area's published API description, so they match
the release you run.

Use the HTTP API when you call Ops AI from a language the SDKs do not cover, or from a system that only speaks HTTP.
Every console screen, SDK call and `opsai` command uses these same routes, under the same permissions.

## Try it

A team admin creates an API key in the console under Settings › API keys. List the team's agents with it:

```bash
curl "https://ops.example.com/api/agents/v1/agents?pageSize=2" \
  -H "X-Api-Key: $OPS_API_KEY" \
  -H "X-Team-Id: team_claims"
```

```json
{"success": true, "data": {"data": [{"id": "agt_...", "name": "Dispute intake"}, {"id": "agt_...", "name": "Fee refunds"}],
  "pagination": {"page": 1, "pageSize": 2, "total": 5, "totalPages": 3, "hasNext": true, "hasPrev": false},
  "facets": {}}}
```

## How it works

| Part | Behaviour |
|---|---|
| Address | One address per install. Each area sits under its own prefix: `/api/platform`, `/api/agents`, `/api/tools`, `/api/kb`, `/api/files`, `/api/documents` |
| Sign-in | An API key in `X-Api-Key`, or a person's session token in `Authorization: Bearer`. A key belongs to one team, is shown once and stored only as a hash; its scopes decide whether it may only read or also write |
| Team | `X-Team-Id` names the team the call acts in; the caller must belong to it |
| Replies | Every success answers `{"success": true, "data": ...}` |
| Lists | `data` holds a page: `data`, `pagination` (`page`, `pageSize`, `total`, `hasNext`, ...) and `facets` (counts per filter value). 20 rows by default, at most 50; follow `pagination.hasNext` for the rest |
| List query | `page`, `pageSize`, `search`, `sortBy`, `sortOrder` (`asc` or `desc`), `ids` (repeated, at most 1000) and the list's own filters, each repeated once per value |
| Errors | Every refusal answers `{"success": false, "error": {"code", "message", "status", "requestId", "details"}}` with the HTTP status of `error.status`. Branch on `code`; quote `requestId` to support |
| Bodies | Request bodies are closed: a field a route does not declare answers 400 `validation_failed` |
| Retries | Reads can be retried. A write is safe to send again only when its route takes an `Idempotency-Key` header and the call sends one |

## The routes

<!-- site: cards -->
| Area | What it covers |
|---|---|
| [Platform](https://opsai.chanl.ai/docs/services/platform-service/api/me/me_me) | You, teams, members, roles, API keys, policies, sign-in providers and the audit log |
| [Agents and workflows](https://opsai.chanl.ai/docs/services/agents-service/api/agents/agents_list_agents) | Agents, workflows, runs, Human tasks, cases, chats and skills |
| [Tools](https://opsai.chanl.ai/docs/services/tools-service/api/apps/apps_list_apps) | Apps, tools, connections, secrets, the egress list and the MCP addresses |
| [Knowledge](https://opsai.chanl.ai/docs/services/kb-service/api/knowledge-bases/knowledge_bases_list_knowledge_bases) | Knowledge bases, sources, items and search |
| [Files](https://opsai.chanl.ai/docs/services/files-service/api/files/files_list_files) | Uploads, downloads, storage settings, retention and legal holds |
| [Documents](https://opsai.chanl.ai/docs/services/documents-service/api/document-types/document_types_list_types) | Document types, readings and extractions |

## Limits

- Model aliases and keys are managed by an account admin in the console or with `opsai models`; the AI gateway's own
  routes are internal.

## Next

<!-- site: cards -->
- **[Python SDK](../sdk/python.md)**: The same routes as typed calls, with paging and retries handled.
- **[The opsai command line](cli.md)**: The same routes from a terminal.
- **[SDK 1.0.0 changelog](../sdk/changelog.md)**: What changed in the routes for 1.0.0.
