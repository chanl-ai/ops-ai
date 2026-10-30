# uc-568 Document workflows

Status: current. Id: `uc-568`. Service: `agents-service`. Layers: api, ui, cli.
Card: an earlier change.

A builder today can read a document only into fields someone has already defined, and can start a workflow only one
run at a time from the console or an API call. So an unknown document, a request from a person outside the console, or
a spreadsheet of 200 cases each needs new code or a person retyping it.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder reads a 12-page scan as full text, page by page, with no model call and only the pages asked for | api | 1-4 | 2 |
| S2 | A builder lets the model propose the fields, renames one, saves them as a document type, and reading the file again with that type gives the same fields | api | 5-7 | 6 |
| S3 | A builder shares a workflow as a form; a submission starts a run in the form's team, and a rotated link, a non-member, or a submission past the rate or the daily cap is refused with why and starts nothing | api | 8-12 | 10 |
| S4 | A builder runs a workflow once per row of a CSV: a dry run first, then progress, Retry failed rows starting only the failed ones, and the results as a CSV | api | 13-16 | 16 |
| S5 | A developer describes a two-source workflow and gets it built from the `two_source_match` example, created only on confirm, and its test run reaches Human review with the disagreements | cli | 21-24 | 23 |
| S6 | A builder does all of this in the console at 1280 and 375 px: the Read dialog and Text tab, Save as document type, Share as a form and the hosted form, Start from a file and the batch page | ui | 31-41 | 40 |

## Preconditions

| Needs | How |
|---|---|
| api: agents-service with files-, documents-, models-service and a workflow worker on the run's database | `models()` on `fake_openai`, `kb(..., models_url=, document_types=True, agents_url=)`, `agents(...)`, a worker with `OPS_FILES_URL`, `OPS_DOCUMENTS_URL`, `OPS_MODELS_URL` |
| A fake model that answers a propose read and the read after it | A rules folder the script writes to a temporary folder: the propose prompt (`Document:` after an optional hint) answers four fields; a `Fields:` prompt naming the scan's marker answers each value with its quote and page |
| A 12-page scan with no text layer | Built with reportlab from page images (Pillow), read with `ocr: true` (Tesseract) |
| ui: the demo stack with the embed app and the three switches on | `withUiStack(..., { demo: true, embed: true, consoleSwitches: { NEXT_PUBLIC_OPS_DOCUMENT_READS: '1', NEXT_PUBLIC_OPS_HOSTED_FORMS: '1', NEXT_PUBLIC_OPS_WORKFLOW_BUILDER: '1' } })` |
| cli: `scripts/wf_builder.py` and two SDK profiles | A temporary `OPS_CONFIG` holding profile `local` and profile `staging`, both on the run's agents-service, each on a fresh team `team_uc568_<hex>`; a profile is local when it is named `local` and its base URL is on this machine |
| People | Dev auth on api and cli (`X-Team-Id: team_ops`; `team_security` is the non-member); James Richardson (team_ops builder) on ui |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | (api) Read the 12-page scan with `read: "text"`, `ocr: true`, no document type | `status: done`; `pages` numbered 1 to 12 in order, each with its `text` and a `tables` list; `text` holds every page's text in page order; the table page's cells read row by row |
| 2 | (api) The same read's cost | No call in models-service's call log for that read, and the read recorded no tokens |
| 3 | (api) Read with `read: "text"`, `maxPages: 3`; then with `read: "nonsense"` | Pages 1 to 3 only, `readPages: 3`; the bad value is refused 400 `validation_failed` |
| 4 | (api) A workflow whose Extract from file step reads `read: "text"`, `maxPages: 2`, run on the scan | It validates clean; the run succeeds with the text of pages 1 and 2 only (a Files read request takes fields or propose, not text) |
| 5 | (api) Read with `read: "propose"`, `hint: "a tax levy notice"` | `proposal` with a name and the four fields; the propose call saw only pages 1 to 5; every value has a quote, a page and a confidence from the checks |
| 6 | (api) Rename `taxpayer` to `debtor_name`; `POST /v1/document-types` with the proposal and `sampleFileId`; read again with that type | 201; the type is listed in team_ops with the file as its first sample and not in team_security; the read gives the same values under the new name |
| 7 | (api) Propose read with `maxTokens` smaller than the scan | `status: done`, `partial: true`, `readPages` under 12 |
| 8 | (api) `POST /v1/workflows/{id}/forms` (link, 30 days, cap 50); the same on a workflow whose trigger has no input form; `GET /v1/forms/public/{slug}?t=` | 201 with id, slug, token, url and an expiry 30 days out; 409 `form_needs_inputs`; the public answer holds only title, description, form and afterText |
| 9 | (api) Upload a file to the form, then submit its values with the file's id | A run starts in team_ops, created by `trigger:form:<id>` and named by the form's title, with the file in its input |
| 10 | (api) Rotate; submit with the old token, with no token, and with another form's token | Each refused 401 `form_link_expired` (or 404 for the other form's token) and starts nothing; the new token works |
| 11 | (api) A members-only form: a team_ops member reads and submits it; a team_security person tries | The member's run is started by that person via "hosted form"; the other is refused 403 `form_members_only` |
| 12 | (api) 11 submissions in a minute from one address while a second address submits; a form with `dailyCap: 2` gets 3 | The 11th from the first address is 429 `form_rate_limited` and the second address still passes; the third is 429 `daily_cap`; Activity shows each refusal with its reason; no run started for any refusal |
| 13 | (api) `POST /v1/workflows/{id}/batches` dry run with a 200-row CSV | `rows: 200`, the mapping of columns to inputs, the ignored column named, the first 5 rows mapped; no run started |
| 14 | (api) A 501-row CSV; a CSV whose header names none of the inputs | 422 `batch_too_many_rows` naming 501; 422 `batch_no_matching_columns` naming the columns; no run started |
| 15 | (api) Start the batch (3 rows are marked to fail) and wait | 202 with an id; `total: 200, finished: 197, failed: 3`; rows list failed first, each with its run |
| 16 | (api) Retry failed rows; download `results.csv` | Exactly 3 new runs, none for a succeeded row; the CSV has a header and 200 rows with the same statuses as the page |
| 17 | (api) The `two_source_match` seed, and a run where two sources disagree with Combine facts `onDisagreement: "port"` | The seed is in `seed/engine_workflows.json` and validates clean; the run leaves Combine facts by `disagree` and waits at Human review with the field the sources disagree on |
| 21 | (cli) `wf_builder.py create --file` dry run on profile `local` from the goal | Writes `workflows/<id>.json`, validated clean, adapted from `two_source_match` (Join, then Combine facts by its disagree port); prints its steps and ports; nothing created |
| 22 | (cli) The same with `--create` on `local` | The workflow exists on the team |
| 23 | (cli) `run <id> --input ... --wait` with disagreeing sources | The run waits at Human review and the output names the disagreements |
| 24 | (cli) `--create` on profile `staging` without the id typed back | Refused; nothing created |
| 31 | (ui) James opens a file's Read dialog | It offers Full text (`file-read-full-text`) and "Let the model propose the fields" (`file-read-propose`) |
| 32 | (ui) Full text, then the Text tab | 12 page entries (`file-text-page`) in order; words under 0.7 confidence are shaded |
| 33 | (ui) Propose, rename a field, Save as document type | The type exists in team_ops with the renamed field |
| 34 | (ui) An Extract from file step's sheet | "What to read" (`step-what-to-read`) offers Fields, Full text and Let the model propose the fields |
| 35 | (ui) Share as a form on the Request trigger | A link (`form-link`), its QR code (`form-qr`, the same image the link makes) with Download QR code, and Rotate (`form-rotate`) |
| 36 | (ui) The link in the embed app (`/f/<slug>?t=`), filled and sent | Only the form's title, description and fields; then the thank-you; a run started |
| 37 | (ui) The rotated link, and a capped form | Each shows why it was refused (`hosted-form-refused`) |
| 38 | (ui) The members-only form in the console (`/forms/<slug>`) | The form for a signed-in member |
| 39 | (ui) Start run, Start from a file, a 12-row CSV, dry run | The row count and the first 5 rows mapped; Start runs; once chosen, the file replaces the drop zone |
| 40 | (ui) The batch page | "N of M finished, K failed" with K = 2; failed rows first; Retry failed rows; Download as CSV gives the table; the bar shows the failed share in the error colour |
| 41 | (ui) The Text tab, the hosted form and the batch page at 375 px | No sideways scroll; the main action on screen |

## Non-vacuous checks

Step 2 fails when a full-text read calls a model. Step 10 pairs the refused old token with the working new one. Step
12 pairs the 11th refused submission with the second address that passes. Step 16 fails when Retry failed rows starts a
succeeded row again. Step 24 fails when a non-local profile creates without the id typed back.
