# Gateway approval token: write tools approved by a token bound to the input

Status: E3, confirmed, 2026-10-10. Holds with real processes and real models; trust is prototype-grade.
Tests: `services/agents-service/tests/gateway/` (the input-hash and crash tests fail on a build with the hash rule
disabled or the claim replaced by a plain insert). Script: `services/agents-service/experiments/e3_gateway_approval_token.py`
(real models, after `make db-up && make migrate`). Policy: `services/tools-service/policy/gateway.rego`.

## Verdict

Every write tool call goes through tools-service (`ops_tools`), where OPA checks an HS256 token bound to thread, step,
tool and the sha256 of the canonical input; the kernel did not change. Interrupts name the exact call they gate
(`call = {tool, input, step}`), and `send_reply` passes the token from its decision.

## What holds

| Failure mode | Result |
|---|---|
| A read needs a token or a gateway hop; an unknown caller or unregistered tool runs | holds |
| A write runs unapproved, or an approved write does not run | holds |
| Input edited after approval (or `24` re-sent as `24.0`), expired token, token from another thread, step or key | holds (refused); reordered keys accepted |
| Money moves on one approver, or one person counted twice | holds |
| A retried write or a crash after the send sends twice; a call goes unlogged; a refusal crashes the turn | holds |
| An approved resume of a gated call arrives without a token | holds (422 `approval_token_required`) |
| SIGKILL in the window between the gateway's answer and the node's checkpoint | not run |

The access class (read, write, money_movement) comes from the registry, never the caller. A unique partial index on
`gateway_calls (thread_id, step, tool, input_hash) WHERE effect` lets one row per approved write run the tool; a retry
returns that row's result and logs a `replayed` row.

## Numbers

Tools service on :8720, agents service on :8723 with real models, OPA 1.21.1 and PostgreSQL from compose:

| Call | Result |
|---|---|
| Read, no token; money with two approvers | 200 allow |
| Write with no token / edited input / expired / other thread / other key; money with one approver | 403, one reason each |
| Dispute resume without token, then with token | 422, then 200 `done`, reply sent |
| Same approved send again | same reference; log rows `ok` (effect) and `replayed` (no effect) |

## Gotchas

| Gotcha | Handling |
|---|---|
| `24` vs `24.0`, `1e21`, `-0`, `NaN`, NFC vs NFD text all hash differently | A second hash implementation follows RFC 8785 (JCS) or calls this one; a normalising proxy causes a (safe) refusal |
| The kernel hands the token to every gated call in the resumed turn | Refused on hash and step; a token covers one call |
| A reviewer edit or a later step changes the hash | Approvals count only rows with the current hash; approve the last version |
| Token is at rest in state and `graph_runs.input`; recovery after its 15-minute TTL is refused | Bounded by binding and TTL; needs a re-review path |
| Gateway dies after claiming, before the tool returns: every retry 409 `write_in_progress` | Needs a reconciler that asks the tool server |
| A process that lost its lease can still send a valid token | Lease generation checked by tools-service (E2b `fencing.md`, E2c `fence-on-takeover.md`) |
| `routers/chat.py` still approves with `dev-approval:<id>` | Chat writes are refused with the gateway on; it is off unless `OPS_GATEWAY_URL` is set |
| `runContext.sub` is caller-asserted; HMAC verifier can mint; key reaches OPA by a data write on :8181 | Production: mTLS identity, asymmetric key, signed bundle |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| Reconciler for `running` gateway rows; re-review path or recovery-aware TTL | Exactly-once writes; recovery of approved writes |
| Chat decide path passes the token; SIGKILL test of the send-to-checkpoint window | Chat approvals; crash guarantee |
| mTLS, asymmetric key, signed OPA bundle | Production trust |
