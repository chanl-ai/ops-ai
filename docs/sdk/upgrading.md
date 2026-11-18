# Upgrading to 1.0.0

Status: current. Version 1.0.0 of both SDKs (`ops-ai` on PyPI, `@chanl-ai/ops-ai` on npm) and the `opsai` command line
follows API changes with no old-name fallback. The full list, route by route, is in [changelog-next-major.md](changelog-next-major.md).
Three patterns cover almost every caller. The Python snippets below are run by `sdk/python/tests/test_upgrading.py`; the TypeScript noun is covered by
`sdk/typescript/test/agents-lists.test.mjs`.

## Lists answer a page of at most 50 rows

Every list route answers `{data, pagination, facets}`. The default page is 20 rows and the largest is 50; a larger
`pageSize` is answered at 50. A caller that read one page, or asked for 100 or 200 rows, now misses rows without an error.
Follow `pagination.hasNext`, or use the nouns, which follow every page for you (`ops.agents.list()`, `ops.apps.list()`).

Python:

```python
# before: rows beyond the first 200 were never seen once the cap fell to 50
rows = ops.raw.agents.agents_list_agents(page_size=200)["data"]

# after: the noun follows every page at 50 rows a page
rows = list(ops.agents.list(search="support"))

# after, with a generated call: follow hasNext yourself
rows, page = [], 1
while True:
    answer = ops.raw.agents.agents_list_agents(page=page, page_size=50, search="support")
    rows += answer["data"]
    if not answer["pagination"]["hasNext"]:
        break
    page += 1
```

TypeScript:

```ts
// after: the noun is an async iterator over every page
const rows = [];
for await (const agent of ops.agents.list({ search: 'support' })) rows.push(agent);
```

A list that pages by cursor (`GET /v1/tools/options`) answers `nextCursor`; `ops.agents.tool_options()` follows it.

## A body with a field the API does not name is refused

Request bodies are typed and closed. A field that is not declared answers 400 `validation_failed` where it used to be
ignored. Send the declared fields only; the nouns do.

```python
# before: the extra field was dropped by the API
ops.raw.agents.batches_start_batch(workflow_id, {"fileId": file_id, "note": "nightly"})

# after
ops.workflows.start_batch(workflow_id, file_id, mode="run")
```

## Errors have one format

Every refusal answers `{success: false, error: {code, message, requestId, details}}` with a status that matches the
code. The SDK turns it into one class per status (`BadRequest`, `NotFound`, `Conflict`, ...). Branch on the class or on
`code`; a 500 that used to stand for a missing team or an unscanned file is now a 400 or 409 with its own code.

```python
# before: a 500 for a file that was not scanned yet
# after
from ops_ai import Conflict

try:
    ops.knowledge.add_page(kb_id, "Title", "text")
except Conflict as refused:
    assert refused.code == "file_not_ready"  # send again after the scan
```
