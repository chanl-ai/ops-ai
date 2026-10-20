# Approval trust: canonical hashes, verified step-up, no self-approval

Status: done, 2026-10-11. Tests: `packages/ops_policy/tests/`, `services/agents-service/tests/api/test_hitl_facade.py`,
`tests/api/test_self_approval.py`, `tests/gateway/test_dispute_e2e.py`; use cases uc-002, uc-008, uc-009.

## Verdict

Approvals now rest on checks that can fail. A forged, expired or borrowed step-up is refused with its reason, the
input hash agrees with RFC 8785, and a money review cannot be approved twice by one person.

## Decisions

| Decision | Detail |
|---|---|
| `packages/ops_policy` holds mechanism only | RFC 8785 canonical JSON, the input hash, signed tokens with expiry behind a `Signer`, step-up mint and verify. Which calls need what stays in the services |
| One canonical form everywhere | `ops_service_kit.ids` delegates to ops_policy, so the kernel, tools-service and approvals hash identically |
| HMAC today, KMS later | `HmacSigner` implements `Signer`; a KMS adapter replaces it without callers changing. Approval tokens stay JWTs because OPA verifies them |
| Step-up key derived per purpose | HMAC of the review key with `"step-up"`: an approval token never verifies as a step-up |
| Dev step-up | `POST /v1/auth/step-up` checks the demo password and mints for the caller; the console's mock sign-in calls it when chat or cases point at the agents service |
| Self-approval | Workflow reviews refuse the requester (the process principal); two-approver money refuses a repeated approver. Chat self-approval is `allow_self_approval_in_chat`, default on: an owner decision is pending, and uc-002 keeps the asker approving |

## Tests, each watched to fail

| Failure mode | Proof |
|---|---|
| `24` and `24.0` hash differently, so a valid approval is refused | `test_number_written_as_float_is_the_same_input`; the old hash refused it |
| NaN accepted | `test_nan_and_infinity_are_rejected` |
| Forged, expired, other person's step-up | Three facade tests; each passed with verification reverted to a presence check, then failed for the right reason once restored |
| Self-approval in chat with the setting off | `test_the_person_who_asked_cannot_approve`, uc-009 |
| Same approver twice on money | `test_money_approval_needs_a_second_person` (403) |

## Gotchas

| Gotcha | Consequence |
|---|---|
| RFC 8785's own sort example uses U+FB33, which NFC rewrites | With NFC on, that key differs from the RFC; the test keeps the RFC order for keys NFC leaves alone |
| A signed step-up is longer than the chat interrupt's 200-character column | Postgres refused it (500) where SQLite tests passed; the decision now records a fingerprint, `su:<sha256>` |
| Chat records the requester by display name | Two people with one name would be treated as one; real identity must use the subject |
| The console decide body carries fields other review kinds use | Accepted and ignored, or the strict wire model answers 400 |
| SSO step-up in the mock still mints locally | Money decisions refuse it when the agents service verifies; only the password path is wired |
| Integers above 2^53 serialise as the double they round to | Matches what a JavaScript verifier reads; exact large ids belong in strings |

## Feeds

[identity-and-tenancy.md](../../../architecture/identity-and-tenancy.md) (shortcut rows updated) and
[human-in-the-loop.md](../../../architecture/human-in-the-loop.md) (rules and token facts updated). Open: the maintainers'
call on chat self-approval, and a KMS `Signer` with only hitl-service able to mint.
