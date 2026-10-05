# ADR-0005 Identity and entitlement

Status: accepted (draft for review). Formerly DR-5.

## Context

The problem statement sets the rule: an agent's entitlement is the intersection of its module scopes and the
entitlements of the person or process it acts for. Module approvals have an owner and an expiry.
Human approval of a drafted action must be provable, and an agent must not be able to perform an
approved-only action without it.

## Options

| Option | Attribution in system-of-record logs | Least privilege | Works for mailbox (no user present) | Score |
|---|---|---|---|---|
| One platform service account | None: every call is "the platform" | No | Yes | 1 |
| Service principal per workflow, no user context | Workflow only | Partly | Yes | 3 |
| Pass the user's token through (impersonation) | User only; the agent is invisible | No: the agent gets all of the user's rights | No | 2 |
| **Workflow identity plus delegation (RFC 8693) and gateway-side intersection** | Both: `sub` is the user or process, `act` is the workflow | Yes | Yes, with a process principal | **5** |

RFC 8693 distinguishes impersonation, where A "becomes" B, from delegation, where actions "remain
attributable to A" acting for B, carried in the `act` claim ([RFC 8693][rfc8693]).

## Decision

| Element | Design |
|---|---|
| Workload identity | Each worker pool and gateway gets a workload identity: SPIFFE/SPIRE (CNCF graduated 2022, [CNCF][spiffe]) or the bank platform's native equivalent (Kubernetes service-account tokens federated to the bank's IdP) |
| Agent identity | Each workflow is registered as a non-human identity in the bank's IdP with an owner, a risk tier and a review date. The identity belongs to the workflow and stays the same across versions, so audit trails stay continuous; the version is a claim |
| Platform identities | Traffic with no workflow runs under its own registered identity with an owner, keys and budgets: one ingestion identity and one playground identity per knowledge base, and one eval identity whose spend is tracked per workflow. These identities can read through the data gateway only under approvals like any workflow, and can never write |
| On-behalf-of | For user-started runs, the trigger exchanges the user's token for a delegation token (`sub` = user, `act` = workflow identity, short expiry, audience = data gateway). For mailbox and scheduled runs, `sub` is a **process principal** owned by the operations team that owns the mailbox, with entitlements that team approved |
| Propagation inside the platform | Short-lived signed context per call; the OAuth Transaction Tokens draft is the closest standard (WG document, revision 11, heading to the IESG in December 2026, [draft][txn-tokens]). Not yet an RFC, so we follow its shape without depending on it |
| Decision point | The data gateway calls a policy engine (OPA, CNCF graduated 2021, [CNCF][opa]) with: workflow identity and version, module name, version and requested operation, the subject's entitlements, the approval record, and any human-approval token |
| Rule | Allow only if (1) an approval exists for this workflow and the module's major version and has not expired, (2) the operation is inside the approved scope, (3) the subject is entitled to it on that resource, (4) the risk-tier rule holds; for `money_movement` access that means a valid human-approval token, and for `write` access a valid human-approval token or policy approval token. An approval binds to the module's **major** version: a minor or patch release reaches a workflow through its next publish, which re-runs its suite and needs no new approval ([ADR-0004](ADR-0004-deployment-tenancy-and-promotion.md#module-versions)) |
| Human-approval token | When a reviewer approves a drafted action, the case service signs a token bound to the case, the action id and a hash of the exact tool input. The gateway rejects the call if the input differs. An agent cannot perform an approved-only action by itself, and an edited action needs a new approval |
| Policy approval token | A gate policy in the workflow version may name write classes (operations with `write` access, for example `mail.send_reply` or a CRM note) and a limit below which drafted actions of that class are approved by the policy. The case service then signs the same token shape, bound to the same input hash, with `approvedBy = policy` plus the policy id and version, which were approved through the publish four-eyes. Allowed only in workflows at effective tier `low` or `medium`; refused at publish for any `money_movement` operation; never issued on an SLA timeout. The case record and audit log show the action as approved by policy |
| Expiry | Checked on every call rather than once at publish. Owners are warned before expiry. An expired approval makes calls fail with a policy error, the run falls into its human step, and the module owner and workflow owner are alerted |

This keeps trust facts out of model-visible text, which [design lessons](../../specs/design-lessons.md) ranks among the top lessons (scope
decided by something the model could influence).

## Consequences

### Strongest counter-argument and our answer

**"Process principals for mailboxes are standing privilege with no human in the loop."** They carry
only the entitlements the owning team approved, those entitlements are scoped per module, and every
write still needs an approval token bound to the exact input. The process principal can read and
draft. It can act without a person only for the non-money write classes a published, four-eyes
approved gate policy names, at `low` and `medium` tier, and never for money movement.

### What would change this decision

- The bank's IdP cannot issue delegation tokens with an `act` claim. Then the gateway mints internal
  delegation tokens itself after authenticating both parties, which concentrates trust in the gateway
  and needs Security's sign-off.
- Systems of record cannot log a second (actor) identity. Then the data gateway's call log becomes
  the only place both identities appear, and Audit must accept it as the record.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Workflow identity in the IdP; platform identities for ingestion, playground and eval; process principal per mailbox; OPA at the data gateway; approval records per major version with expiry checked per call; human and policy approval tokens bound to the action input | User delegation via token exchange (needed once chat or user-started runs exist, ADR-0009); SPIFFE if the platform lacks native workload identity; Transaction Tokens if the draft becomes an RFC |

## Sources

[opa]: https://www.cncf.io/projects/open-policy-agent-opa/
[rfc8693]: https://www.rfc-editor.org/rfc/rfc8693.html
[spiffe]: https://www.cncf.io/projects/spiffe/
[txn-tokens]: https://datatracker.ietf.org/doc/draft-ietf-oauth-transaction-tokens/
