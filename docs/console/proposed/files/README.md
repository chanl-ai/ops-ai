# File page and Extract, proposed

Status: proposed, waiting for approval. Built from `docs/services/documents-service/design.md` screens 1
to 3, on the stack's real fixtures (TEST012.pdf, a synthetic restraining notice) and the demo's fake model. uc-227
takes these screenshots; once approved they move to `docs/console/approved/files`.

| Screen | 1280 px | 400 px |
|---|---|---|
| A file not read yet | [file-preview-unread-1280](https://opsai.chanl.ai/docs/console/proposed/files/file-preview-unread-1280.png) | |
| Extract | [extract-dialog-1280](https://opsai.chanl.ai/docs/console/proposed/files/extract-dialog-1280.png) | |
| Preview after a read: the PDF with the fields beside it | [file-preview-1280](https://opsai.chanl.ai/docs/console/proposed/files/file-preview-1280.png) | [file-preview-400](https://opsai.chanl.ai/docs/console/proposed/files/file-preview-400.png) |
| Fields | [file-fields-1280](https://opsai.chanl.ai/docs/console/proposed/files/file-fields-1280.png) | [file-fields-400](https://opsai.chanl.ai/docs/console/proposed/files/file-fields-400.png) |
| Files with Read as | [files-read-as-1280](https://opsai.chanl.ai/docs/console/proposed/files/files-read-as-1280.png) | |
| Field boxes on the page, a field and its box selecting each other | [file-preview-boxes-1280](https://opsai.chanl.ai/docs/console/proposed/files/file-preview-boxes-1280.png) | |
| A corrected value with what was read beside it | [file-fields-corrected-1280](https://opsai.chanl.ai/docs/console/proposed/files/file-fields-corrected-1280.png) | |
| Fields restyled, before and after | [fields-look-fields-side-by-side](https://opsai.chanl.ai/docs/console/proposed/files/fields-look-fields-side-by-side.png), [fields-look-preview-side-by-side](https://opsai.chanl.ai/docs/console/proposed/files/fields-look-preview-side-by-side.png) | |

Differences from the design, and why:

| Difference | Why |
|---|---|
| Detect is listed but disabled | Classify's backend is not built yet |
| Document type is a select, not the entity picker | Document types have no `/options` route; a team has a handful |
| No Suggest template action | Templates are not built yet |
