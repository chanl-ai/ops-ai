# A builder manages a tool module

Status: current. Id: `uc-010`. Service: `tools-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Nothing else | The script starts tools-service on its own database, seeded with the console's modules |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `POST /v1/tool-modules/blank` | 201, a draft |
| 2 | Add an HTTP operation whose Authorization header holds a literal token | 400 |
| 3 | Add it again with `{{STATEMENTS_TOKEN}}` as the header value, before its host is on the egress allow-list | 422 |
| 4 | List the host under `/v1/egress/hosts`, then add the operation again | 200, the module lists the operation |
| 5 | `POST .../reviews` | the draft moves to `in_review` |
| 6 | Change a rate limit on Core banking and publish | the next minor version is published |
| 7 | Request a workflow approval, decide it as the requester, then as someone else | 403, then `approved` |
| 8 | Restart tools-service and read both modules again | the draft, its operation and the approval are still there |

Editing a published operation's call (c-027), against the https fake bank through `/v1/calls`:

| # | Step | Expected |
|---|---|---|
| 9 | Edit the path to another origin; edit a header to a literal credential | 400 each, nothing staged |
| 10 | Edit the path to `/v1/statements/latest` and call before publishing | the published call answers (the account) |
| 11 | Publish | the next major version |
| 12 | Set a transform; call; set a failing one; call | the shaped answer; then the answer plus `transform_error`, 200 |
| 13 | Path `/v1/slow` (answers after 3 s) with `timeoutMs` 1000; call | `UPSTREAM_TIMEOUT` naming 1000 ms, an error row in executions |
| 14 | Restart and read the operation | the edited path and timeout are kept |

In the console (ui layer), with Tools pointed at tools-service: open a published operation's sheet; its HTTP section
shows the call; a URL off the endpoint cannot be staged; a path that drops `{accountId}` warns that the input is
unused; Stage change sends only the path as one major change; the version holds until Publish, which makes the next
major and opens a security review. Screenshots: `evidence/027/`.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-010-api.py` | passing |
| ui | `tools-service/scripts/test-uc-010-ui.mjs` | passing |

## Non-vacuous check

`the requester cannot decide their own request (403)` paired with `someone else approves it`: if every decision were
refused, or every one allowed, one of the pair fails. The restart checks fail if the registry kept anything in memory.
Step 10 fails if staged call-shape edits are live (the call reaches `/v1/statements/latest`, which answers 401 without
a key); at the ui layer, the blocked off-endpoint URL pairs with the staged path edit that follows.
