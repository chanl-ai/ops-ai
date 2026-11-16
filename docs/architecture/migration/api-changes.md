# API changes in the standards migration

Status: current, 2026-11-15. Each service's API document changes where the standards call for it: the shared list
contract and its paging ([components.md](components.md), C2), typed bodies and replies (C5) and the standard error
reply. Old parameter names, filters and reply shapes are not kept. The console's data layer, both SDKs and the CLI are
updated later in this migration from this page; in-repo service clients and api-layer use-case scripts change in the
same commit as the route.

Each service has a table: one row per change, with what a caller must change. "Old form works" says whether a caller
that has not changed still gets the same answer.

## files-service

| Route | What changed | Before | After | What a caller must change | Old form works |
|---|---|---|---|---|---|
| `GET /v1/files` | parameter `pageSize` | default 25, at most 100 (a larger value refused with 422) | default 20 (`OPS_PAGE_SIZE_DEFAULT`), a larger value than 50 (`OPS_PAGE_SIZE_MAX`) answered at 50 | Ask for 50 or fewer per page and follow `pagination.hasNext`; send `pageSize` when 25 was relied on | Partly: a size of 51 to 100 now gives 50 rows instead of the size asked for |
| `GET /v1/files` | parameters `sortBy`, `sortOrder`, `ids` | absent | `sortBy` `name` or `uploadedAt`, `sortOrder` `asc` or `desc` (default `desc`), `ids` repeated for exact rows whatever the search says | Nothing; new | Yes |
| `GET /v1/files` | parameter `search` | string, default `""` | string or null, unset by default | Nothing | Yes |
| `GET /v1/files` | `page` past the last page | an empty `data` with that page number | the last page, with its page number in `pagination.page` | Read `pagination.page` | Partly |
| `GET /v1/files` | reply field `facets` | a value with no read-as type or read path counted under the key `"None"` | null values not counted | Do not read `facets.readAs.None` or `facets.readPath.None`; files with no reading are the total minus the counts | Partly |
| `PUT /v1/files/{file_id}/data` | body schema name | `FileData`, also the reply's `data` | `FileDataIn`; the reply's `FileData` keeps the fields without the length and range limits | Nothing in the JSON; a generated-SDK caller names `FileDataIn` | Yes |
| `PUT /v1/settings/storage`, `POST /v1/settings/storage/test` | body schema names | `StorageDocument`, `StorageTarget`, `PurposeLimit`, `PurposeRetention`, each also in the reply | `StorageDocumentIn`, `StorageTargetIn`, `PurposeLimitIn`, `PurposeRetentionIn`; the reply models keep their names without the body's limits | Nothing in the JSON; a generated-SDK caller of `settings_test_target` names `StorageTargetIn` | Yes |
| `POST /v1/files/{file_id}/download-url` | body | `DownloadIn` or null, optional | `DownloadIn`, optional, `{}` when absent | Nothing: no body, `{}` and a JSON `null` each get a link of the longest life (null checked by hand, 200) | Yes |
| `GET /v1/files` | reply schema of each row | `scan`, `retention`, `legalHold`, `storage` described as free objects | described as `FileScan`, `FileRetention`, `LegalHold`, `StorageLocation`, as on the detail | Nothing; the values are the same | Yes |
| `GET /v1/settings/storage`, `PUT /v1/settings/storage` | reply schema of `retentionClasses` | free objects | `RetentionClassView` (`id`, `name`, `days`) | Nothing; the values are the same | Yes |

### Follow-ups for the SDK and console steps (files-service)

| Where | What to change |
|---|---|
| `sdk/python/src/ops_ai/_cli/testdata.py:21` (`PAGE = 100`) | `_pages` stops when a page holds fewer than `PAGE` rows, so with the cap of 50 it reads only the first 50 test files; set `PAGE = 50` or stop on `pagination.hasNext` |
| `sdk/python/src/ops_ai/_generated/files/operations.py`, `sdk/typescript/src/generated/files*.ts` | Regenerate: `files_list_files` gains `sortBy`, `sortOrder`, `ids`; `pageSize` loses its default and maximum |
| Typed bodies and replies | The generated layer is regenerated in the same commit; no hand-written SDK noun, CLI verb or console file calls `files_set_file_data` or `settings_test_target`, and the console's own types in `apps/console/src/lib/types/files.ts` read the same JSON, so none must follow |
| `apps/console/src/lib/api/files-service-http.ts:30` (`list`) | Send `sortBy`/`sortOrder` from the table's sort; keep `pageSize` at 50 or less |

## models-service

| Route | What changed | Before | After | What a caller must change | Old form works |
|---|---|---|---|---|---|
| `GET /v1/models/calls` | behaviour: calls that name no tenant | listed with every tenant's calls (before the call log was held to its tenant) | not listed: a completion sent with no `X-Tenant-Id` is kept in `model_calls_untenanted` for operators and no route reads it | Send `X-Tenant-Id` on every completion whose calls must be listed | No |
| `GET /health/background` | new route | absent | the service's background processes (`models_spend_retention`, the sweep of idle key spend) and their state, as every service answers it | Nothing; new | Yes |
| `GET /health` | reply model | an open object | `Health`: `status` only, no other field | Nothing | Yes |
| `POST /v1/models/chat/completions` | reply field `choices[].message.tool_calls` | each call passed on as the provider sent it, any key included | `ToolCall`: `id`, `type` `function`, `function` {`name`, `arguments`}, OpenAI's names unchanged; a key outside OpenAI's format is not passed on | Nothing for an OpenAI client | Yes |

## documents-service

| Route | What changed | Before | After | What a caller must change | Old form works |
|---|---|---|---|---|---|
| `POST /v1/documents/extractions` | behaviour: files-service fails after the extraction is saved | the request failed and the row stayed `queued`, so a retry with the same `Idempotency-Key` answered 202 `queued` until the process restarted | the row is settled `failed` (`error.code` `failed`), so a retry with the same key runs it again at once | Nothing | Yes |
| `GET /v1/document-types` | shared list contract | `{items, canCreate}`, every type of the team | `DocumentTypeList`: `{data, pagination, facets, canCreate}`, one page (`page`, `pageSize`, `search` on the name, `ids`), by name then key | Read `data` and page with `pagination.hasNext`. Follow: console `apps/console/src/hooks/document-type-queries.ts`, `apps/console/src/lib/types/document-types.ts` (`items` to `data`); `ops_documents_client.document_types()` pages (done) | No |
| `GET /v1/documents/extractions` | shared list contract | `page`, `pageSize` 1 to 100 (above refused), ties by asked time then id ascending | `ListQuery`: `pageSize` above the install maximum (50 by default) answers at the maximum; `search`, `sortBy`, `ids` accepted; ties by id descending; the reply shape is unchanged | Nothing unless asking for more than 50 a page. Follow: console `apps/console/src/lib/types/extractions.ts` (check its page size) | Yes |
| `GET /health` | reply model | an untyped object `{status, reason?}`; the 503 body was written by hand | `Health`: `status` `ok` or `degraded`, `reason` `database` or `ocr` or absent, no other field; the same bodies on 200 and 503 | Nothing | Yes |
