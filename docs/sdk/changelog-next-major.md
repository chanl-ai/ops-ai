# SDK 1.0.0 route-by-route record

Status: current, 2026-11-17. For contributors: each changed route with the code that follows it. Callers read the
[SDK 1.0.0 changelog](changelog.md) instead.

Both SDKs (`ops-ai` 0.1.0 to 1.0.0, `@chanl-ai/ops-ai` 0.1.0 to 1.0.0) and the `opsai` command line (it ships in `ops-ai`)
take the major version; the number is in `sdk/python/pyproject.toml`, `sdk/python/src/ops_ai/__init__.py` and
`sdk/typescript/package.json`, and `.github/workflows/sdk-publish.yml` publishes a version that is not on its registry
yet. The "Breaking changes" block below is generated from `docs/architecture/migration/api-changes.md` by
`sdk/changelog_from_api_changes.py` (one line per route whose old form does not fully work); do not edit it by hand.
How to change a caller: [upgrading.md](upgrading.md). The tables below name the hand-written nouns and CLI verbs that
follow each route.

<!-- breaking:start (sdk/changelog_from_api_changes.py) -->
## Breaking changes

### every service

- Every list route (`ListQuery`: today `GET /v1/files`, `GET /v1/document-types`, `GET /v1/documents/extractions`, `GET /v1/models/calls`): parameter `ids`. Ask for 1000 ids or fewer per call; a picker with more asks in batches. Follow: none known; no console screen, hand-written SDK noun or CLI verb sends more than a page of ids. Old form works: yes, up to 1000.

### files-service

- `GET /v1/files`: parameter `pageSize`. Ask for 50 or fewer per page and follow `pagination.hasNext`; send `pageSize` when 25 was relied on. Old form works: partly: a size of 51 to 100 now gives 50 rows instead of the size asked for.
- `GET /v1/files`: `page` past the last page. Read `pagination.page`. Old form works: partly.
- `GET /v1/files`: reply field `facets`. Do not read `facets.readAs.None` or `facets.readPath.None`; files with no reading are the total minus the counts. Old form works: partly.

### models-service

- `GET /v1/models/calls`: behaviour: calls that name no tenant. Send `X-Tenant-Id` on every completion whose calls must be listed. Old form works: no.
- `GET /v1/models/calls`: shared list contract. Read `data` and page with `pagination.hasNext`; send `page` instead of `limit`. Done in the same change: `tests/conftest.py` `Models.calls`, use cases uc-028, uc-060, uc-250, uc-568, uc-605 (`usecase_harness.every_page`), `services/agents-service/experiments/e13_models_service_hop.py`. Console, hand-written SDK nouns and CLI: none call this route; models-service has no generated SDK layer. Old form works: no.
- `GET /v1/models/providers`, `GET /v1/provider-keys`, `GET /v1/models/aliases`, `GET /v1/models/aliases/{name}/versions`, `GET /v1/models/keys`: shared list contract. Read `data` and page with `pagination.hasNext`, or ask for the rows wanted with `ids` or `search`. Done in the same change: `services/agents-service/src/ops_agents/api/model_aliases.py` (every page), `services/documents-service/src/ops_documents/document_types.py` (the price now reads `GET /v1/models/aliases?ids=<alias>`, the serving version), `services/models-service/tests/conftest.py` `spent()`, use cases uc-060 (api), uc-605 (api, cli), `deploy/fly/connect_model.py`, `scripts/demo_model.py`, `scripts/demo_salesforce.py`, `scripts/sample_team.py`. Follow: `services/documents-service/experiments/measure_page_images.py` (reads `data` as an array; the file carries tracker ids the public-view hook refuses, so it is left to its owner), console `apps/console/src/lib/api/provider-connections-http.ts` and `apps/console/src/lib/api/provider-keys-http.ts` (`list` reads a bare array; Settings > Model providers), the hand-written SDK noun `sdk/python/src/ops_ai/_models.py` (`providers`, `keys`) and its CLI verbs, and the ui use-case scripts `docs/usecases/models-service/scripts/test-uc-532-ui.mjs`, `test-uc-605-ui.mjs`, `test-uc-720-ui.mjs` and `docs/usecases/platform-service/scripts/test-uc-751-ui.mjs`, which read `data` as an array; models-service has no generated SDK layer. Old form works: no.

### documents-service

- `GET /v1/document-types`: shared list contract. Read `data` and page with `pagination.hasNext`. Follow: console `apps/console/src/hooks/document-type-queries.ts`, `apps/console/src/lib/types/document-types.ts` (`items` to `data`); `ops_documents_client.document_types()` pages (done); `apps/console/src/app/data/document-types/page.tsx:281` (`query.data.items.map` now throws: `items` is gone), `apps/console/src/components/files/extract-dialog.tsx:53` (`types.data?.items ?? []`), `apps/console/src/lib/api/files-http.ts:28` (`list: () => get(base)` asks the first page only), `sdk/python/src/ops_ai/_cli/records.py:88` (`ops types` reads the first page only). Old form works: no.

### platform-service

- `GET /v1/settings/members`: paging. Follow `pagination.hasNext` in a team of more than 20 people. Follow: console `apps/console/src/lib/api/settings-http.ts:13` and `platform-access-http.ts:60` send the table's page, size, search and sort; CLI `sdk/python/src/ops_ai/_cli/people.py:41` pages with `page_items` past the first 20; `scripts/sample_team.py:223`, `:274`, `:313` and `scripts/sample_walk.py:117` read one page (their teams hold fewer than 20). Old form works: partly: a team of more than 20 answers its first 20.
- `GET /v1/settings/members`: reply field `facets`. Nothing for an unfiltered list. Old form works: partly.
- `GET /v1/api-keys`: reply and paging. Read the rows from `data.data` and follow `pagination.hasNext`. Follow: console `apps/console/src/lib/api/platform-http.ts:77` reads `data.data` and pages; no hand-written SDK noun or CLI verb lists keys. Old form works: no: the reply is an object, not a list.
- `GET /v1/settings/teams`: paging and order. Follow `pagination.hasNext` past 20 teams; send `status=active` to see active teams first. Follow: console `apps/console/src/lib/api/workspace-teams-http.ts:17` already sends page, size, search and status; `scripts/sample_team.py:206`, `scripts/sample_walk.py:103` and `scripts/team_isolation_probe.py:228` search one name; no hand-written SDK noun or CLI verb lists teams. Old form works: partly: a workspace of more than 20 teams answers its first 20.
- `GET /v1/audit`: paging. Follow `pagination.hasNext` and stop on it, not on an empty page. Follow: console `apps/console/src/lib/api/platform-access-http.ts:83` sends the table's page size (check it is at most 50); `docs/usecases/platform-service/scripts/test-uc-025-api.py:40` asks 200 and reads the newest 50; no hand-written SDK noun or CLI verb reads this route. Old form works: partly: more than 50 a page answers 50.
- `GET /v1/roles`, `GET /v1/roles/{roleId}/holders`, `GET /v1/people/{personId}/role-grants`: reply and paging. Read the rows from `data.data` and follow `pagination.hasNext`. Done in the same change: `docs/usecases/platform-service/scripts/test-uc-118-api.py`. Follow: console `apps/console/src/lib/api/platform-http.ts:21`, `:28`, `:29` read a bare array (`useRoles`, `useRoleHolders` and the person's grants in `apps/console/src/hooks/me-queries.ts:52`, `:84`, `:89`; types in `apps/console/src/lib/api/contract.ts:306`, `:308`); no hand-written SDK noun or CLI verb reads these routes. Old form works: no: the reply is an object, not a list.
- `GET /v1/roles/{roleId}/holders`: `ids` and order. Send the holder `id` the reply shows. Follow: none; no console screen, SDK noun or CLI verb sends `ids` here. Old form works: no: an assignment id now answers no row.
- `GET /v1/access/holders`, `GET /v1/policies`, `GET /v1/policies/{key}`, `GET /v1/people/{personId}/role-grants`, `GET /v1/people/{personId}/permissions`, `GET /v1/people-names`, `GET /v1/team-names`: who may read. Nothing for any role but Chat user, whose screens read none of these. Follow: none. Old form works: no, for a chat user only: 403 `admin_required`.
- `GET /v1/teams`: reply, paging and order. Read `data.data` and follow `pagination.hasNext`, or ask by `ids` or `search`. Follow: console `apps/console/src/hooks/use-team.ts` (the current and own team by `ids`, the switcher, palette and team fields search through `teamOptions` in `hooks/options-queries.ts`, labels through `useTeamsNamed`); a person whose remembered team is gone lands on their own team, else the first by name instead of the first they joined; both SDK `teams` nouns follow pages; uc-164, `docs/usecases/lib/capture_demo.mjs` and `scripts/demo-salesforce/walk.mjs` search by name. Old form works: no.

### kb-service

- `GET /v1/knowledge-bases`, `GET /v1/sources`, `GET /v1/sources/{source_id}/runs`, `GET /v1/sources/{source_id}/items`: parameter `pageSize`. Ask for 50 or fewer per page and follow `pagination.hasNext`; send `pageSize` when 25 was relied on. Follow: the console's `useKnowledgeBases`, `useSources`, `useSourceItems` and `useSourceRuns` in `apps/console/src/hooks/knowledge-queries.ts` (calls in `apps/console/src/lib/api/knowledge-http.ts`); the CLI's `kb bases`, `kb sources` and `kb items` in `sdk/python/src/ops_ai/_cli/kb.py`, which read one page of 50 and must follow `pagination.hasNext`; the hand-written list noun in `sdk/python/src/ops_ai/_client.py`. Done in the same change: `docs/usecases/kb-service/scripts/test-uc-080-api.py`, `test-uc-675-api.py`, `test-uc-678-api.py` and `docs/usecases/agents-service/scripts/test-uc-590-api.py` read every page of a source's items. Old form works: partly: a size of 51 to 100 now gives 50 rows instead of the size asked for.
- `GET /v1/knowledge-bases/{kb_id}/documents`: parameter `pageSize`; how the page is made. Ask for 50 or fewer per page and follow `pagination.hasNext`. Follow: the console's documents table (`apps/console/src/hooks/knowledge-queries.ts` `kk.documents`, call in `apps/console/src/lib/api/knowledge-http.ts` `kbs.documents`) pages through `usePagedQuery`; no hand-written SDK method or CLI verb calls it. Old form works: partly: a size of 51 to 100 now gives 50 rows.
- `GET /v1/knowledge-bases`: parameter `templateId`. A generated-SDK caller passes `templateId` as an extra query key. Follow: none known; no console screen, hand-written SDK method or CLI verb sends it. Old form works: yes, over http.
- `POST /v1/sources`: status when the caller resolves to no team. Name the team with `X-Team-Id`. Follow: none; every in-repo caller names a team. Old form works: no: 500 before.
- `POST /v1/sources/{source_id}/items`, `POST /v1/knowledge-bases/{kb_id}/pages`: status for a file stored but not scanned clean yet. Treat 409 `file_not_ready` as "send again after the scan" or wait for the next sync. Follow: none required; no console screen, hand-written SDK method or CLI verb branches on these statuses. `apps/console/src/components/knowledge/add-data-source.tsx` (page dialog) and `sdk/python/src/ops_ai/_client.py` `put_item` show the error's message as they show any refusal. Old form works: no: 500 before.
- `POST /v1/sources/{source_id}/items`, `POST /v1/knowledge-bases/{kb_id}/pages`: status for an item a rule of the source leaves out, or content the source already holds under another name. Change the name, the content or the source's rules. Follow: as the row above. Old form works: no: 500 before.
- Every body: `POST`/`PATCH /v1/knowledge-bases`, `POST /v1/knowledge-bases/{kb_id}/sources`, `/query`, `/pages`, `/documents`, `POST /v1/knowledge-bases/search`, `POST`/`PATCH /v1/sources`, `POST /v1/sources/preview`, `/scopes`, `/{source_id}/files`, `/items`, `/sync`, `/ai-approval`, `/tombstones/lift`, `POST /v1/knowledge-changes/decide`, `PATCH /v1/knowledge-changes/{change_id}`, `POST /v1/items/{item_id}/verify`, `PUT /v1/items/{item_id}/owner`: unknown body fields. Send only the declared fields, one spelling each. Done in the same change: `docs/usecases/kb-service/scripts/test-uc-675-api.py` (sent `type` beside `config` on the preview). Follow: none known; `apps/console/src/lib/api/knowledge-http.ts` sends the declared fields (its `sources.create` spreads `sync` and `kbIds`, both declared), and `sdk/python/src/ops_ai/_client.py` passes a caller's own `**fields` through to `sources_create_source` and `sources_put_item`, which now refuse a misspelt one. Old form works: partly: a body with an unknown field now answers 400.
- `GET /v1/knowledge-bases/options`, `GET /v1/knowledge-bases/{kb_id}/documents`, `GET /v1/sources`, `GET /v1/sources/{source_id}`, `/tombstones`, `/runs`, `/items`, `GET /v1/knowledge-changes`, `GET /v1/knowledge-changes/{change_id}`, `GET /v1/sync-runs/{run_id}`, `GET /v1/knowledge/lookups`: callers. Nothing for people and keys; no service calls these routes. Follow: none. Old form works: yes, for people and keys.
- `PATCH /v1/knowledge-bases/{kb_id}`: body. Send only declared fields. Old form works: no.
- `POST /v1/knowledge-bases/{kb_id}/query`: body. Send only declared fields. Old form works: no.
- `POST /v1/sources/{source_id}/sync`: body. Send only `full` and `retry`. Old form works: no.
- `POST /v1/sources/scopes`, `POST /v1/sources/{source_id}/ai-approval`, `POST /v1/sources/{source_id}/files`, `POST /v1/sources/{source_id}/tombstones/lift`: body. Send only declared fields. Old form works: no.

### tools-service

- `GET /v1/apps/{app}/resources`, `GET /v1/plugin-templates`; agents-service and documents-service `GET /v1/templates`, their copy routes and agents-service `POST /v1/resources/plan`: a template's `copy`, `installed` and `requires` are shared models. In the tools SDK the generated types `ResourceCopy` and `ResourceInstalled` are `CopyRef` and `Installed`. In the agents and documents SDKs a copy's `kind` is typed as all eight resource kinds (six before in agents, `document_type` alone in documents), so code that switches over it must allow the rest. In the agents SDK `detachedAt` is required on a copy, and in the agents and tools SDKs `installed.changed` and `requires.resources` are required (optional before, always sent). Follow: none; no console file or hand-written SDK noun names these types or switches on a copy's `kind`. Old form works: no for generated type names and the wider `kind`; yes on the wire.
- `GET /v1/tool-catalog`: module event fields. A receiver must accept the new fields before tools-service sends them: `ops_store.outbox` payloads refuse unknown fields (`extra="forbid"`), so agents-service deploys first. Follow: agents-service's copy (`services/agents-service/src/ops_agents/store/tool_copies.py`) skips a `truncated` event and resyncs the tenant. Old form works: no: an agents-service built before this change refuses the new fields.
- `GET /v1/egress/hosts`: shared list contract. Ask for 50 or fewer per page and follow `pagination.hasNext`, or name the hosts wanted with `search` or `ids`. Done in the same change: `docs/usecases/tools-service/scripts/test-uc-010-api.py` (asked 200 a page; now searches its one host). Follow: console `apps/console/src/lib/api/egress-http.ts:15` (`hosts`, Settings > Security > Egress, `apps/console/src/app/settings/security/egress/page.tsx:97`) keeps its page size at 50 or less; `docs/usecases/console/scripts/test-uc-710-ui.mjs:104` asks 50 (unchanged); no hand-written SDK noun or CLI verb reads this route (`opsai egress list` reads `GET /v1/egress`). Old form works: partly: a size of 51 to 200 now gives 50 rows.
- `GET /v1/tool-modules/{module_id}/operations/{op_id}/mocks`: shared list contract. Read `data` as before and follow `pagination.hasNext` past 20 mocks. Done in the same change: none needed (`docs/usecases/tools-service/scripts/test-uc-397-api.py` adds three). Follow: console `apps/console/src/hooks/systems-queries.ts:204` (`tool_modules_list_mocks`, the operation's Mock answers panel) reads the first page only; no hand-written SDK noun or CLI verb reads this route. Old form works: partly: an operation with more than 20 mocks answers its first 20.
- `GET /v1/mcp-links`: shared list contract. Read the links from `data.data` and follow `pagination.hasNext` past 20 links. Done in the same change: none needed (`docs/usecases/tools-service/scripts/test-uc-410-api.py` and `test-uc-410-ui.mjs` only make links). Follow: console `apps/console/src/lib/api/mcp-links-contract.ts:5` (`list(): Promise<McpLink[]>`), `apps/console/src/lib/api/mcp-links-http.ts:9` and `apps/console/src/hooks/mcp-link-queries.ts:16` (`useMcpLinks`, Build > Channels > MCP, `apps/console/src/components/channels/mcp/links-page.tsx:37`) read the page; no hand-written SDK noun or CLI verb reads this route. Old form works: no: the reply is an object, not an array.
- `GET /v1/secrets`: shared list contract. Read the rows from `data.data`; a picker searches (`search`) or names (`ids`) the secrets it needs instead of loading every one, and a list follows `pagination.hasNext`. Done in the same change: `docs/usecases/tools-service/scripts/test-uc-013-api.py` (names its secret with `ids`), `test-uc-615-api.py` and `test-uc-392-api.py` (follow every page). Follow: console `apps/console/src/lib/api/secrets-http.ts:12` and `secrets-contract.ts:9` (`list(): Promise<SecretMeta[]>`), `apps/console/src/hooks/secrets-queries.ts:12` (`useSecrets`), read by `apps/console/src/components/shared/secret-picker.tsx:21` and `apps/console/src/components/channels/mailbox-fields.tsx:112`, which must search as a person types instead of loading every secret; `apps/console/src/components/secrets/secrets-panel.tsx` (Settings > Secrets) now also lists an account's secret parts, read only, and needs a label or link for them as it has for an auth config's; hand-written SDK nouns `sdk/python/src/ops_ai/_words.py:117` and `:797` and `sdk/typescript/src/words.ts:56` (`secrets.list()`, which now answers the first page only through `_rows`/`rowsOf`), and the CLI verb `opsai secrets list` (`sdk/python/src/ops_ai/_cli/secrets.py:31`), page or search. Old form works: no: the reply is a page, not an array.
- `GET /v1/tool-modules/grants`: shared list contract. Ask for 50 or fewer and follow `pagination.hasNext`. Follow: console `apps/console/src/lib/api/tool-modules-http.ts:15` and `apps/console/src/hooks/tool-module-queries.ts:49` (`useToolGrants`, Govern > Access > Tool access, `apps/console/src/app/govern/access/tool-access/page.tsx:57`) keep a page size of 50 or less; no hand-written SDK noun or CLI verb reads this route. Old form works: partly: a size of 51 to 100 gives 50 rows; the first page holds 20 by default.
- `GET /v1/tool-modules`: shared list contract. Ask for 50 or fewer and follow `pagination.hasNext`; send `sortOrder=asc` for an ascending sort. Done in the same change: `services/tools-service/scripts/reimport_bank_module.py` (follows every page), `docs/usecases/tools-service/scripts/test-uc-617-ui.mjs` (asks 50 with its search). Follow: console `apps/console/src/lib/api/tool-modules-http.ts:16` (`list`) and `apps/console/src/app/data/tools/custom/page.tsx:182` (`useToolModules`, Build > Tools) keep 50 or less and send `sortOrder`; no hand-written SDK noun or CLI verb reads this route. Old form works: partly: a size of 51 to 200 gives 50 rows; `sortby` alone now sorts descending.
- `GET /v1/apps`: shared list contract. Read the cards from `data.data`; a picker names (`ids`) or searches (`search`) the cards it needs, a whole list follows `pagination.hasNext`. Done in the same change: agents-service `services/agents-service/src/ops_agents/activities/tool_directory.py` (`ToolsApps.cards`, every page), `docs/usecases/console/scripts/test-uc-607-api.py` and `test-uc-607-ui.mjs`, `docs/usecases/tools-service/scripts/test-uc-564-api.py`, `test-uc-564-cli.py`, `test-uc-583-api.py`, `test-uc-584-api.py`, `test-uc-588-api.py`, `test-uc-625-ui.mjs`, `test-uc-628-ui.mjs`, `docs/usecases/lib/connection_calls.py`. Follow: console `apps/console/src/hooks/systems-queries.ts:37` (`useSystems`, the Apps grid, which must page and search on the server) and `:92` (`useConnectionOptions`, the module's app picker, which must search or name), `apps/console/src/hooks/options-queries.ts:63` (`appOptions`, which can pass its `search` and `ids` straight through); hand-written SDK nouns `sdk/python/src/ops_ai/_words.py:162` and `:499`, `sdk/typescript/src/words.ts:120` (`apps.list()`), the CLI verb `opsai apps list` (`sdk/python/src/ops_ai/_cli/apps.py:81`, `make apps-list`) and `docs/usecases/console/scripts/test-uc-607-sdk.py` step 24, which reads them. Old form works: no: the reply is a page, not an array.
- `PATCH`, `DELETE /v1/tool-modules/{module_id}`, `POST /v1/tool-modules/bulk-delete`, `POST .../operations`, `.../operations/import`, `.../functions`, `PATCH .../operations/{operation_id}`, `PUT .../connection`, `POST .../versions`, `DELETE .../pending-changes`, `POST .../reviews`, `.../approvals/revoke`, `.../approvals/{approval_id}/decide`, `POST`, `PATCH`, `DELETE .../operations/{op_id}/mocks...`: who may change a module. Nothing for the owning team. A grant team that changed the module now asks its owner. Follow: none; the console offers these actions on the owner's pages. Old form works: no: the grant team gets 404.
- `POST /v1/tool-modules/{module_id}/test`, `POST .../operations/{operation}/run`: who may try a module's tools. Nothing for the owning team. Follow: none; the console's tool pages (`apps/console/src/app/data/tools/[id]/operations/[op]/page.tsx`, `useTestModule` in `apps/console/src/hooks/tool-module-queries.ts:29`), the CLI and use cases uc-011, uc-038, uc-564 and uc-611 call them as the owning team. Old form works: no: the grant team gets 404.
- `POST /v1/calls` (every write a tool makes: agents, workflows, MCP, a tool page's Real run): behaviour: the team's approval rules cannot be read. Retry a 503 `approval_rules_unavailable` once platform-service answers; set `OPS_PLATFORM_URL` for tools-service. Done in the same change: `scripts/stack.sh` passes it in dev auth too (the dev stack runs platform-service). Use-case stacks that start tools-service without platform-service now have every write refused (uc-610 step 4 among them). Follow: the console shows the error message of a refused call as it does any other; no SDK noun or CLI verb names the code. Old form works: no.
- `POST /v1/calls`, `POST /v1/code-runs/calls`, `GET /v1/grantable-operations`, MCP `tools/list` and `tools/call`: what a cross-team grant opens (behaviour, no shape change). Re-request an ended grant, or one for each operation a workflow needs. Follow: none; no console screen, hand-written SDK noun or CLI verb changes. Old form works: no, by design.
- `POST /v1/calls`, `GET /v1/grantable-operations` (a service token naming no team): which approval level a write follows (behaviour, no shape change). Name the run's team; no production caller sends none (agents-service runs and turns, kb-service, MCP and code runs all name one). Follow: none. Old form works: no, by design.
- `GET /v1/tools/{name}`: who may read it. Nothing for agents-service (its tools client already claims `tools:view`, `services/agents-service/src/ops_agents/api/app.py` `PUBLIC_SCOPES`); a test or script token must claim the scope. No console screen, hand-written SDK method or CLI verb calls it. Old form works: no.
- `PATCH /v1/tool-modules/{module_id}/operations/{op_id}/mocks/{mock_id}`: reply `data` and body. Send only declared fields. Old form works: partly.

### agents-service

- `GET /reviews` (and `GET /v1/overview`'s review counts, a task's place in its queue): rows read per source. Nothing while each source holds fewer rows than the cap. Above it, the oldest decided reviews (and, past the cap in open ones, the oldest open ones) leave the list, the view counts and the stats. Follow: none; no console screen, hand-written SDK noun or CLI verb changes. Old form works: yes, while each source is under the cap.
- `POST /v1/workflows/{workflow_id}/forms`, `PATCH /v1/forms/{form_id}`, `POST /v1/forms/public/{slug}/submit`, `POST /v1/forms/{slug}/members`: bodies on the kit's `In`; one transaction per builder route; a link's tenant checked. Send only the declared fields: `mode`, `expiresInDays`, `dailyCap`, `title`, `description`, `afterText`; `paused`, `dailyCap`, `afterText`; `values`. Follow: none; the console (`apps/console/src/components/workflows/definition-editor/share-as-form.tsx:66`, `apps/console/src/lib/api/forms-http.ts`), the embed page (`apps/embed/src/hosted-form-page.tsx:56`) and use cases uc-568 and uc-620 send only these; no hand-written SDK noun or CLI verb calls these routes. Old form works: yes, unless a caller sent an undeclared field.
- `GET /v1/widgets`: shared list contract. Read `data` and page with `pagination.hasNext`, or ask for the pins wanted with `ids`. Follow: console `apps/console/src/lib/api/widgets-http.ts:12` (`list` reads a bare array) and its reader `useWidgetTemplates` (`apps/console/src/hooks/widget-queries.ts:14`, the agent page `apps/console/src/app/build/agents/[id]/page.tsx:169`); ui use cases `docs/usecases/console/scripts/test-uc-097-ui.mjs`, `test-uc-103-ui.mjs`; no hand-written SDK noun or CLI verb calls it. Old form works: no.
- `GET /v1/skills`: shared list contract. Page with `pagination.hasNext` instead of asking for 200. Done in the same change: tools-service `mcp_tools.py` (`PAGE` 50, `MAX_PAGES` 80, the MCP prompts), `scripts/sample_team.py` (`every_row`). Follow: console `apps/console/src/lib/api/skills-http.ts:32` (the chat menu asks `pageSize=200` and reads one page); the Skills page's list hook; the generated SDK layer is regenerated; no hand-written SDK noun or CLI verb calls it. Old form works: no.
- `PATCH /v1/agents/{agent_id}`, `PUT /v1/skills/{skill_id}/draft`, `GET /v1/agents/{agent_id}`, `GET /v1/skills/{skill_id}`, `PUT` and `DELETE /v1/agents/{agent_id}/skills/{skill_id}`: a save names the copy it was made on. Read the agent or skill, then send its `version` and `digest` with the save; on 409 read again and repeat. Python `agents.update(id, fields)` and `skills.save_draft(id, fields, base=)`, TypeScript `agents.update` and `skills.saveDraft(id, fields, { base })`, and `opsai agents apply` and `skills apply` do this. Python `skills.save_draft` no longer takes `base_version`, and TypeScript `skills.saveDraft` no longer takes the `baseVersion` option; pass `base` in both. Old form works: no.
- `GET /v1/guardrails`: shared list contract. Read `data` and page with `pagination.hasNext`, or ask for the pins wanted with `ids`; the picker already reads `GET /v1/guardrails/options`. Done in the same change: `scripts/sample_team.py` (`every_row`). Follow: console `apps/console/src/lib/api/guardrails-http.ts:12` (`list` reads a bare array) and its readers; the generated SDK layer is regenerated; no hand-written SDK noun or CLI verb calls it. Old form works: no.
- `GET /v1/agents`: shared list contract. Ask for 50 or fewer and follow `pagination.hasNext`; send `sortOrder=asc` with `sortBy` for an ascending sort; pass `templateId` as a query key, not the generated argument. Follow: console `apps/console/src/hooks/queries.ts:50` (`useAgents`, Build > Agents `apps/console/src/app/build/agents/page.tsx:73`) keeps 50 or less; the embed dialog's agent picker `apps/console/src/components/deployments/widget-embed.tsx:36` (`PUBLISHED`, read at `:78`) asks 100 published agents and now gets the first 50 with no sign of more, so it must search on the server or follow `pagination.hasNext`; hand-written SDK nouns `sdk/python/src/ops_ai/_agents.py:53` and `:204`, `sdk/typescript/src/agents.ts:25` already follow every page. Old form works: partly: a size of 51 to 200 gives 50 rows; `sortby` alone now sorts descending.
- `GET /v1/workflows`: shared list contract. Nothing for the row; a pager that asks past the end gets the last page. Follow: none; the console's Workflows list (`apps/console/src/hooks/queries.ts:54`), the tool page's approval picker (`apps/console/src/app/data/tools/[id]/page.tsx:87`) and the runner runs filter (`apps/console/src/components/workflows/runner-runs.tsx:79`) read it unchanged. Old form works: yes, but for a page past the end.
- `GET /v1/cases`: shared list contract. Ask for 50 or fewer and follow `pagination.hasNext`. Follow: console `apps/console/src/hooks/case-record-queries.ts:12` (`useCaseRecords`, Work > Cases `apps/console/src/app/work/cases/page.tsx:53`) keeps 50 or less; the CLI `sdk/python/src/ops_ai/_cli/records.py:37` already asks for 50; `docs/usecases/lib/capture_demo.mjs:90`, `:316` ask for 50. Old form works: partly: a size of 51 to 100 gives 50 rows, and the default page holds 20.
- `GET /v1/case-types`, `GET /v1/task-types`: shared list contract. Read the types from `data` and follow `pagination.hasNext`, or name them with `ids`. Done in the same change: `docs/usecases/agents-service/scripts/test-uc-254-api.py` (every page). Follow: none; no console screen, hand-written SDK noun or CLI verb lists them. Old form works: no: the reply is a page, not an array.
- `GET /v1/workflows/{workflow_id}/forms`: shared list contract. Read the forms from `data` and follow `pagination.hasNext`. Follow: console `apps/console/src/lib/api/forms-http.ts:10` (`list` reads a bare array), its hook `apps/console/src/hooks/form-queries.ts:15` (`useWorkflowForms`) and the workflow editor's Share as form panel `apps/console/src/components/workflows/definition-editor/share-as-form.tsx:47`; the embed app reads only the public form routes; no use-case script, hand-written SDK noun or CLI verb lists them. Old form works: no: the reply is a page, not an array.
- `GET /v1/runs`: shared list contract. Send `workflowId`, not `workflow_id`; ask for 50 or fewer and follow `pagination.hasNext`. Done in the same change: `docs/usecases/agents-service/scripts/test-uc-209-api.py` (`every_page`), `test-uc-245-ui.mjs` and `test-uc-249-ui.mjs` (every page). Follow: none; the console `apps/console/src/lib/api/engine-http.ts:22` asks for 25 with `workflowId`, the CLI `sdk/python/src/ops_ai/_cli/runs.py:45` asks for 50 with the generated `workflow_id` and `status` arguments. Old form works: partly: a size of 51 to 100 gives 50 rows, the default page holds 20, and `workflow_id` is ignored.
- `GET /v1/workflows/definitions`: shared list contract. Ask for 50 or fewer and follow `pagination.hasNext`. Follow: no console screen reads this list; hand-written SDK noun `sdk/python/src/ops_ai/_workflows.py:82` (`Workflows.list`) already follows every page; `docs/usecases/platform-service/scripts/test-uc-563-cli.mjs:70` asks for 50. Old form works: partly: a size of 51 to 200 gives 50 rows, and the default page holds 20.
- `GET /v1/threads`: shared list contract; who reads which thread decided in SQL. Read `data` and page with `pagination.hasNext`. Done in the same change: agents-service route tests, `docs/usecases/agents-service/scripts/test-uc-003-api.py`, `docs/usecases/console/scripts/test-uc-058-api.py` (`every_page`), `test-uc-058-ui.mjs` (every page). Follow: none; no console screen reads this list (`apps/console/src/lib/api/cases-http.ts:28` only creates a thread); the hand-written SDK noun `threads` (`sdk/python/src/ops_ai/_client.py:87`, `sdk/typescript/src/client.ts:94`) already follows every page; no CLI verb lists threads. Old form works: no: the reply is a page, not an array.
- `GET /v1/threads/{thread_id}/inbox`: who reads it. Nothing for the thread's reader. No service, poller or channel worker calls this route (the mailbox workers read the store). Follow: none; no console screen, hand-written SDK noun or CLI verb reads it. Old form works: no: a teammate who cannot read the thread gets 404 instead of 200.
- `POST /v1/publish-requests` (a person's tool module review), `POST /v1/publish-requests/egress-hosts`: the service token in `X-Service-Authorization`. tools-service's agents client for reviews asks for `tools:publish` (`services/tools-service/src/ops_tools/__main__.py`, done in the same change). Follow: none; no console screen, hand-written SDK noun or CLI verb calls these routes. Old form works: no: a tools-service token without the scope is refused.
- `GET /v1/runs?workflowId=`: `workflowId` repeatable. The generated TypeScript type is `string[]`. Follow: `apps/console/src/hooks/engine-queries.ts:122` and `EngineRunsParams.workflowId` (`apps/console/src/lib/types/engine.ts:189`) pass one string and must pass an array; the CLI's `opsai runs list --workflow` (`sdk/python/src/ops_ai/_cli/runs.py:44`) sends one value, which still works. Old form works: no in typescript (type); yes on the wire.
- `POST /v1/agents/{agent_id}/eval-runs`: body. Send only `cases`; another field answers 400 `validation_failed`. Old form works: no.
- `POST /v1/workflows/definitions/validate`: body `definition`. Send the fields the definition declares. Old form works: partly.
<!-- breaking:end -->

Every list route now answers the shared page (`data`, `pagination`, `facets`): the default page is 20 rows and the largest
is 50. Both SDKs page through `every_page` (Python, `ops_ai._transport`) and `everyPage` (TypeScript, `transport.ts`),
which follow `pagination.hasNext` and ask for 50 rows a page. Old parameter names and old reply shapes are gone, with no
aliases.

## Hand-written nouns and CLI verbs

| Python | TypeScript | Command line | Change |
|---|---|---|---|
| `ops.apps.list(connected, search, ids)` | `ops.apps.list({connected, search, ids})` | `opsai apps list [--connected] [--search]` | follows every page of `GET /v1/apps`; `search` and `ids` are new |
| `ops.secrets.list(search, ids)` | `ops.secrets.list({search, ids})` | `opsai secrets list [--search]` | follows every page of `GET /v1/secrets`; rows now include an account's secret parts, marked `readOnly` |
| `ops.models.providers(search)`, `ops.models.keys(search)` | none | `opsai models providers`, `opsai models keys` | follow every page; `search` is new |
| `ops.raw.platform.members_list_members` | same | `opsai people list`, `opsai people roles` | every page of members and roles, not the first 20 |
| `ops.raw.files.files_list_files` | same | `opsai files list`, `opsai test-data clean` | every page, 50 rows a page (was 100, which now answers at 50) |
| `ops.raw.documents.document_types_list_types`, `documents_file_extractions` | same | `opsai documents types`, `opsai documents extractions` | every page; the types reply is `{data, pagination, facets, canCreate}` |
| `ops.raw.kb.*_list_*` | same | `opsai kb bases`, `documents`, `sources`, `items`, `changes`, and `--kb` names in chat scripts | every page, 50 rows a page |
| `ops.raw.tools.tool_modules_list_modules` | same | `opsai tools list` | every page |

## Routes

### files-service

| Route | Change |
|---|---|
| `GET /v1/files` | `pageSize` default 20 and largest 50 (was 25 and 100); new `sortBy` (`name`, `uploadedAt`), `sortOrder`, `ids`; a `page` past the end answers the last page; `facets` no longer counts a `None` key |
| `PUT /v1/files/{file_id}/data` | body type is `FileDataIn` |
| `PUT /v1/settings/storage`, `POST /v1/settings/storage/test` | body types `StorageDocumentIn`, `StorageTargetIn`, `PurposeLimitIn`, `PurposeRetentionIn` |
| `POST /v1/files/{file_id}/download-url` | body optional, `{}` when absent |
| `GET /v1/files` (row), `GET`/`PUT /v1/settings/storage` (`retentionClasses`) | typed rows: `FileScan`, `FileRetention`, `LegalHold`, `StorageLocation`, `RetentionClassView` |

### models-service

| Route | Change |
|---|---|
| `GET /v1/models/calls` | `CallPage` (`data`, `pagination`, `facets`, `byKey`); `limit` is gone, send `page`; calls with no tenant are not listed |
| `GET /v1/models/providers`, `GET /v1/provider-keys`, `GET /v1/models/aliases`, `GET /v1/models/aliases/{name}/versions`, `GET /v1/models/keys` | shared page; `ids` and `search` |

### documents-service

| Route | Change |
|---|---|
| `GET /v1/document-types` | `DocumentTypeList`: `data` replaces `items`; one page; `search`, `ids`, `sortBy`, `sortOrder` |
| `GET /v1/documents/extractions` | shared `ListQuery`: page size at most 50 |
| Readings and extraction replies | generated types narrower; `Page`, `Block` and the like are named `Reading...` |

### runner-service

| Route | Change |
|---|---|
| `POST /v1/runs` | typed `output`; a tool slower than the run's limit now fails the call |

### platform-service

| Route | Change |
|---|---|
| `GET /v1/me` | reply carries `permissions` |
| `GET /v1/settings/members` | paged (20, at most 50) with `search`, `sortBy`, `ids`; `facets` |
| `GET /v1/api-keys` | `data` is a page; follow `pagination.hasNext` |
| `GET /v1/settings/teams` | paged; `status=active` lists active teams first |
| `GET /v1/audit` | at most 50 a page; stop on `pagination.hasNext`, not on an empty page |
| `GET /v1/roles`, `GET /v1/roles/{roleId}/holders`, `GET /v1/people/{personId}/role-grants` | a page, not an array |
| `GET /v1/roles/{roleId}/holders` | `ids` matches the holder `id` the reply shows |
| `POST /v1/settings/members/invite`, `POST /v1/settings/members/role` | `role` accepts `chat_user` |

### kb-service

| Route | Change |
|---|---|
| `GET /v1/knowledge-bases`, `GET /v1/sources`, `GET /v1/sources/{id}/runs`, `GET /v1/sources/{id}/items` | `pageSize` default 20, largest 50; `sortBy`, `sortOrder`, `ids`; `search` on runs |
| `GET /v1/knowledge-bases/{kb_id}/documents` | `pageSize` at most 50 |
| `GET /v1/knowledge-bases` | `templateId` is a filter given once per value |
| `POST /v1/sources` | no team resolved answers a refusal; send `X-Team-Id` |
| `POST /v1/sources/{id}/items`, `POST /v1/knowledge-bases/{kb_id}/pages` | 409 `file_not_ready` for a file not yet scanned clean; refusals for items a source's rules leave out |
| Every kb body | unknown body fields answer 400; send only declared fields |

### tools-service

| Route | Change |
|---|---|
| `GET /v1/egress/hosts` | shared page; `search`, `ids`; at most 50 a page (was 200) |
| `GET /v1/tool-modules/{module_id}/operations/{op_id}/mocks` | a page: follow `pagination.hasNext` past 20 mocks |
| `GET /v1/mcp-links` | a page: `data.data` and `pagination` |
| `GET /v1/secrets` | `SecretList` page; `search`, `ids`; one form only (the bare array is gone) |
| `GET /v1/tool-modules/grants` | at most 50 a page (was 100); `view` as before |
| `GET /v1/tool-modules` | at most 50 a page (was 200); `sortOrder=asc` for an ascending sort; `templateId` is a list of values |
| `GET /v1/apps` | `SystemCardList` page, not an array; `search`, `ids` |
| `POST /v1/fences`, `POST /v1/mailboxes/*`, internal routes | typed bodies and replies; not in the public SDK |

### agents-service

| Route | Change |
|---|---|
| `GET /v1/agents` | `pageSize` default 20, largest 50 (was 25 and 200); `ids`; `sortBy` alone sorts descending (send `sortOrder=asc`); `templateId` is no longer an argument of the generated call; search is case-insensitive on name, role and slug |
| `GET /v1/skills` | `SkillList`: `pageSize` default 20, largest 50 (was 25 and 200); `search`, `ids`; a page past the end answers the last page |
| `GET /v1/guardrails` | always a page (`data`, `pagination`, `facets`), never a bare array; `pageSize` 20 and 50; `search`, `ids` |
| `GET /v1/widgets` | always a page, never a bare array; `pageSize` 20 and 50; `search`, `ids` |
| `GET /v1/workflows/{workflow_id}/forms` | a page, not an array; `search`, `ids` |
| `GET /v1/cases` | `pageSize` default 20, largest 50 (was 25 and 100); `ids`; `sortBy` and `sortOrder` change nothing |
| `GET /v1/case-types`, `GET /v1/task-types` | a page, not an array; `search`, `ids` |
| `GET /v1/runs` | `pageSize` default 20, largest 50 (was 25 and 100); `ids`; newest first, then id descending; the `workflow_id` spelling is gone, send `workflowId` (the generated argument stays `workflow_id`) |
| `GET /v1/threads` | a page, not an array; `ids`; `sortBy=updatedAt` with `sortOrder`; only threads the caller may read are counted |
| `GET /v1/threads/{thread_id}/inbox` | a teammate who cannot read the thread gets 404 `not_found` (was 200) |
| `GET /v1/workflows/definitions` | `pageSize` default 20, largest 50 (was 25 and 200); `ids`; `status` |
| `GET /v1/workflows`, `GET /v1/workflows/{workflow_id}/runs` | `status` is a declared, repeated parameter |
| `POST /v1/workflows/{workflow_id}/batches` | an unknown body field answers 400 `validation_failed`; the body is `fileId`, `mode`, `dryRun` |
| `POST`, `PATCH` form routes (`/v1/workflows/{workflow_id}/forms`, `/v1/forms/{form_id}`, `/v1/forms/public/{slug}/submit`, `/v1/forms/{slug}/members`) | an unknown body field answers 400 `validation_failed`; a link token for another tenant answers 404 |

Hand-written nouns and verbs added or changed for these routes:

| Python | TypeScript | Command line | Change |
|---|---|---|---|
| `ops.agents.list`, `ops.cases.list`, `ops.runs.list`, `ops.tasks.list`, `ops.threads.list`, `ops.workflows.list` | same, as async iterators | `opsai agents list [--search]`, `opsai cases list`, `opsai runs list`, `opsai tasks list`, `opsai workflows list [--status]` | every page, 50 rows a page; no first-page-only reads and no page size above 50 |
| `ops.skills`, `ops.guardrails`, `ops.widgets`, `ops.case_types`, `ops.task_types` | `ops.skills`, `guardrails`, `widgets`, `caseTypes`, `taskTypes` (`list`, `get`) | `opsai skills\|guardrails\|widgets list [--search] [--id]`, `opsai cases types`, `opsai tasks types` | new nouns |
| `ops.workflows.forms(workflow_id)` | `ops.workflows.forms(workflowId)` | `opsai workflows forms <id>` | new |
| `ops.workflows.start_batch(workflow_id, file_id, mode, dry_run)` | `ops.workflows.startBatch(workflowId, fileId, {mode, dryRun})` | `opsai workflows batch-start <id> --file-id` | new; sends only the declared fields |
| `ops.threads.inbox(thread_id)` | `ops.threads.inbox(threadId)` | `opsai threads inbox <id>` | new; 404 for a thread the caller cannot read |
| `ops.threads.list` | same | `opsai threads list [--graph] [--id]`, `show` | new CLI area |
