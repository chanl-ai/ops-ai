# File page and Extract, proposed

Status: proposed, waiting for approval. Built by c-262 from `docs/services/documents-service/design.md` screens 1
to 3, on the stack's real fixtures (TEST012.pdf, a synthetic restraining notice) and the demo's fake model. uc-227
takes these screenshots; once approved they move to `docs/console/approved/files`.

| Screen | 1280 px | 400 px |
|---|---|---|
| A file not read yet | [file-preview-unread-1280](file-preview-unread-1280.png) | |
| Extract | [extract-dialog-1280](extract-dialog-1280.png) | |
| Preview after a read: the PDF with the fields beside it | [file-preview-1280](file-preview-1280.png) | [file-preview-400](file-preview-400.png) |
| Fields | [file-fields-1280](file-fields-1280.png) | [file-fields-400](file-fields-400.png) |
| Files with Read as | [files-read-as-1280](files-read-as-1280.png) | |
| Field boxes on the page, a field and its box selecting each other | [file-preview-boxes-1280](file-preview-boxes-1280.png) | |
| A corrected value with what was read beside it | [file-fields-corrected-1280](file-fields-corrected-1280.png) | |
| Fields restyled, before and after | [fields-look-fields-side-by-side](fields-look-fields-side-by-side.png), [fields-look-preview-side-by-side](fields-look-preview-side-by-side.png) | |

Differences from the design, and why:

| Difference | Why |
|---|---|
| Detect is listed but disabled | Classify arrives with c-250's backend |
| Document type is a select, not the entity picker | Document types have no `/options` route; a team has a handful |
| No Suggest template action | Templates arrive with c-247 |
