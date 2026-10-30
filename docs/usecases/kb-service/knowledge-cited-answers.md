# A banker asks an agent and gets an answer cited by page and section from uploaded PDFs

Status: passing. Id: `uc-080`. Service: `kb-service`. Layers: api. Card: an earlier change.

The card's tasks name uc-074 for this layer; uc-074 was already the console's chat-thread use case, so this one takes
the next free id.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| kb-service on its own migration chain, uploads in a temporary folder | started by the script (`kb(files_dir)`) |
| agents-service on the scripted model, searching that kb-service | started by the script (`agents(kb_url=...)`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Create a knowledge base with no owner | 400 `collection_without_owner` |
| 2 | Create it with an owner, a file source attached to it, upload two text PDFs and a scanned page, sync | the two text PDFs indexed with their page counts; the scan failed with `no_text_layer`; the run `partial` |
| 3 | Ask the knowledge base how many payments a borrower who lost their job may defer | first citation: Mortgage Hardship Policy, page 1, section Eligibility |
| 4 | Ask about the weather in Lisbon | no citation, `noAnswer` |
| 5 | Upload a new rate sheet under the same name, sync, ask for the fixed rate | every citation is v2; the old rate (4.89) is gone |
| 6 | Read the Changes feed for the knowledge base | one row, v1 to v2 |
| 7 | An agent granted the knowledge base answers the step 3 question in chat | the reply cites page 1, section Eligibility; the thread names the knowledge base |
| 8 | An agent not granted it opens a thread on it | refused (422, "cannot search") |

The scripted model cites `[1]` on any turn that carries passages and has no other script (`tests/conftest.py`), so
step 7 checks that kb-service's passage reaches the reply with its page and section, not a model's wording.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-080-api.py` | passing |

In the console: uc-075's ui script turns a department's PDFs into an answer cited by page and section.

## Non-vacuous check

Step 7 was seen failing (no citations) while the scripted model cited only questions about wire limits, although
kb-service answered the search; it passes once the passage reaches the reply. Steps 3 to 6 cannot pass without
kb-service: agents-service's fixture store holds none of these documents.
