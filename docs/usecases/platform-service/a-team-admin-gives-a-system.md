# A team admin gives a system its own expiring, rotatable key limited to picked tools, and the call log names that system

Status: draft. Id: `uc-721`. Service: `platform-service`, tools-service, console. Layers: api, ui.

Labels from the MCP sign-in design: step 1 is uc-mcp-10, step 2
uc-mcp-9, step 3 uc-mcp-12, step 4 uc-mcp-11, step 5 uc-mcp-13, step 6 uc-mcp-18; the ui steps are uc-mcp-13 and uc-mcp-20.
The registry only takes `uc-NNN` ids, so one use case carries all of them.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team admin gives a script a key that ends in 30, 90 or 365 days, and a member cannot | api | 1 | 1 |
| S2 | The script runs the tools the admin picked and no others, and the call log names the script and who made its key | api | 2, 3 | 2 |
| S3 | The admin rotates the key and the old secret ends after a day, or at once | api | 4 | 4 |
| S4 | The key keeps working when its maker leaves, and a key that starts runs is still made | api | 5, 6 | 5 |
| S5 | The admin makes a key with picked tools, sees it expire soon, rotates it, and sees a gone maker | ui | 7, 8, 9 | 8 |
| S6 | A member sees no access, and the page says so when the list is empty or fails | ui | 10 | 10 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

platform-service runs with the dev seed's own roles; tools-service verifies its keys through introspection
(`OPS_AUTH_MODE=platform`). No model is called.

## Names the tests fix

| What | Name |
|---|---|
| Create body | `expiresInDays` required, 1 to 365; `tools` the tool names the key may run; `scopes` stays read or write |
| Rotate | `POST /v1/api-keys/{id}/rotate`, body `{stopNow?}`; answers `{key, secret, graceEndsAt}`, `graceEndsAt` null for stop now |
| Introspection | `sub` `key:<id>`, `name` the key's name, `apiKey` `{id, target, tools, makerEmail}` |
| Key list row | `tools`, `makerGone` |
| Call log | `gateway_calls.key_name`, `gateway_calls.key_maker`; the refusal code is `insufficient_scope` |
| Audit | `key.create`, `key.rotate`, `key.revoke` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A builder, then an admin, make a key; the admin leaves out the expiry, then asks for 366 days | 403 for the builder; 4xx for both bad bodies; 201 with the secret once |
| 2 | The key runs the picked tool and another read through tools-service | The other read is refused with `insufficient_scope`; the call log row names the key, its name and its maker |
| 3 | A key picked for a write tool calls it | `insufficient_scope`, no hold |
| 4 | Rotate; then Rotate with stop now | New secret works; old works until the grace ends; stop now refuses the old one within the 30-second key cache |
| 5 | The key's maker is removed from the team | The key still works; the list says `makerGone` |
| 6 | An admin makes a write key for a workflow | 201 with the target |
| 7 | (ui) The admin opens Create key | A tool picker, and no "Never" choice for expiry |
| 8 | (ui) A key 10 days from its end, one with a gone maker | "Expires soon" at 1440 and 390; the maker shown as gone; Rotate in the row menu shows a new secret once |
| 9 | (ui) The admin rotates and revokes | The row shows the change |
| 10 | (ui) A member opens the page; the list is empty; the list fails | No-access state; empty state; error state |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-721-api.py` | failing (red) |
| ui | `platform-service/scripts/test-uc-721-ui.mjs` | failing (red) |

## Non-vacuous check

Each step fails today for the reason the card names: the rotate route and the `tools` field do not exist, a key is
accepted without an expiry, the log names the maker, and a key stops when its maker leaves.
