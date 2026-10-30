# A builder adds documents to a knowledge base by uploading them or picking them from Files

Status: passing. Id: `uc-129`. Service: `kb-service`. Layers: ui. Card: an earlier change.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| platform, agents, kb and files services on the run's database; the console signed in as James | `withUiStack(..., { platform: true })` |
| A PDF already in Files | uploaded to files-service by the script before the console opens |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open a new base | no Documents tab; Sources offers Add documents |
| 2 | Add documents: upload a PDF and pick the PDF already in Files | the upload goes to files-service (`/v1/files/uploads`); one `POST /v1/knowledge-bases/{id}/documents` with both file ids; both indexed |
| 3 | Reload the base | the documents source is active and counts two indexed items (read from the API); its row shows on Sources |
| 4 | Read both files in Files | each is referenced by the source, so Files keeps it |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `kb-service/scripts/test-uc-129-ui.mjs` | passing |

## Non-vacuous check

With the console's files-service client as it was before an earlier change, step 2 failed: no upload reached files-service
(`/v1/files/uploads` not called within 60 seconds), because uploads went to the in-browser API.
