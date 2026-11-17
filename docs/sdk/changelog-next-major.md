# SDK changes for the next major version

Status: draft, 2026-11-16. The version number is not bumped yet; one bump happens at the end of the standards
migration. Entries come from `docs/architecture/migration/api-changes.md`, one per changed route, for the services
whose API work is finished: platform, kb, documents, files, models, runner and tools. Agents-service is not listed yet.

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
