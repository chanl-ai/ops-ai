# A scanned file attached in chat is read with OCR and reaches the agent whole

Status: current. Id: `uc-673`. Service: `agents-service`. Layers: api, ui.

A file attached to a chat message is read through the file's reading in documents-service, with OCR on auto
(`OPS_ATTACHMENTS_OCR`), and every page of it goes to the model in the attachments block, within the turn's share of
24,000 characters, rather than the three 2,000-character pieces a knowledge search returned. The agent cites a page of
the file by its number. The file is a two-page scan made by the script: no text layer, words only in the pictures.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A banker attaches a scanned fee schedule and the agent is given both pages of it | api | 1, 2 | 2 |
| S2 | The banker asks what a replacement card costs and the answer cites page 2 of the scan | api | 3 | 3 |
| S3 | The scan was read once, with OCR, by documents-service | api | 4 | 4 |
| S4 | In the console the banker attaches the scan, asks, and sees the answer cite page 2 | ui | 1 | 1 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Tesseract with English | `brew install tesseract` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Upload the two-page scan to Files as a chat attachment | stored and scanned clean |
| 2 | Send "How many pages did you get?" with the file attached | the scripted model, which counts the numbered pages in the attachments block, answers "2 pages" |
| 3 | Send "What does a replacement debit card cost?" | the reply cites the file (its file id) on page 2 |
| 4 | Read the file's reading from documents-service | done, both pages read by `ocr` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-673-api.py` | passing |
| ui | `agents-service/scripts/test-uc-673-ui.mjs` | passing |

## Non-vacuous check

Step 2: with the attached pages cut to the old three-piece cap or read with OCR off, the model is given fewer pages or
none; `services/agents-service/tests/api/test_chat_attachments.py::test_a_long_attached_file_reaches_the_model_whole_and_is_read_with_ocr`
was seen failing both ways.
