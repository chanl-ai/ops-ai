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
| `GET /v1/files` | order of rows with the same upload time | then by id | in the database's order (the list contract's default sort is one column) | Nothing for the Files page; a caller that pages through rows uploaded in the same instant may see one twice or miss one | Partly |

### Follow-ups for the SDK and console steps (files-service)

| Where | What to change |
|---|---|
| `sdk/python/src/ops_ai/_cli/testdata.py:21` (`PAGE = 100`) | `_pages` stops when a page holds fewer than `PAGE` rows, so with the cap of 50 it reads only the first 50 test files; set `PAGE = 50` or stop on `pagination.hasNext` |
| `sdk/python/src/ops_ai/_generated/files/operations.py`, `sdk/typescript/src/generated/files*.ts` | Regenerate: `files_list_files` gains `sortBy`, `sortOrder`, `ids`; `pageSize` loses its default and maximum |
| `apps/console/src/lib/api/files-service-http.ts:30` (`list`) | Send `sortBy`/`sortOrder` from the table's sort; keep `pageSize` at 50 or less |
