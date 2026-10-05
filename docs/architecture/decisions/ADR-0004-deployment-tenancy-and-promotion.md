# ADR-0004 Deployment, tenancy and promotion

Status: accepted (draft for review). Formerly DR-4.

## Context

The platform runs inside the bank on private cloud or on-prem Kubernetes (OpenShift is common in
banks; the bank's choice is [open question 1](../overview.md#open-questions)). Reasons 6 and 7 of the [problem statement](../../background/problem-statement.md) say one runtime replaces
per-agent servers, secrets and logging, and promotion moves a version pointer instead of waiting
for a release window.

## Options

| Option | Isolation | Operating cost | Fits problem statement risk tiers | Score |
|---|---|---|---|---|
| One shared worker pool | Weak: a low-risk workflow's dependency shares a process with payment actions | Lowest | No | 2 |
| **Worker pools per risk tier** | Separate Kubernetes namespaces, service identities, network policies and task queues per tier | Low: three or four pools | Yes, tier is the control the gate already uses | **5** |
| Worker pools per department | Matches org chart; data isolation is already enforced at the gateway | Grows with departments | Partly | 3 |
| Worker pool per workflow | Strongest | Recreates Reason 6 (each agent gets its own servers) | Over-fits | 2 |

## Decision

| Concern | Choice |
|---|---|
| Environments | Exactly three. `dev`: authors build drafts, run server checks, the agent Test sheet and draft sample mail in test mode with writes stubbed; no release pointer and no deployments. `test`: gate eval runs, sample-mail runs, test mailboxes, smoke checks and the `test` release pointer, moved on publish approval. `production`: live runs and the `production` pointer. The mock's "staging" is `test` |
| Clusters | Separate Temporal clusters for production and non-production; namespaces `dev` and `test` on the non-production cluster |
| Worker pools | One per risk tier (`low`, `medium`, `high`, `critical`), each on its own task queue, Kubernetes namespace and workload identity. A department with a regulatory segregation requirement may get a dedicated pool within its tier |
| Egress | Default-deny network policy. Workers reach the Temporal frontend, the data gateway, the AI gateway and the object store, and nothing else. Only the gateways have routes to bank systems and model endpoints. This turns "all model traffic through the AI gateway" from a policy into a network fact |
| Secrets | A secret store the bank already runs; if none, OpenBao (Linux Foundation fork of Vault under MPL 2.0, [summary][openbao], secondary) or HashiCorp Vault under its BSL licence. Credentials for bank systems live only in the data gateway's scope; workers hold none |
| Payload protection | Temporal payload codec encrypts inputs and outputs, so the Temporal server and its database never hold plaintext customer data; large payloads (emails, attachments, model outputs) go to the object store and only references enter history, which also keeps runs under the 51,200-event and 50 MB history limit ([limits][temporal-limits]) |
| Operator access | Temporal authoriser configured with JWT claims per namespace (the default allows everything, [security][temporal-sec]); Temporal UI behind the bank's SSO; production namespaces read-only for humans except break-glass |
| Tiers promoted to production | Phase 1 promotes only `low` and `medium` workflows to production, because staged rollout comes later. `high` follows once the Model Risk second-line approver group (`04` S8) is named; `critical` waits for staged rollout. A phase-1 workflow therefore cannot include a `money_movement` action, because that raises the inherited tier to `high` (`01` 5.2) |
| Test results in the gate | Structural errors, evidence-integrity failures and the injection threshold block at every tier. At `medium` and above, failing tests block. At `low`, tests are advisory: every failing test needs a written reason per failure from the approver (see [Advisory tests at the lowest tier](#advisory-tests-at-the-lowest-tier)) |

### How "promotion moves a version pointer" works on Temporal

There are two kinds of version, and they move by different mechanisms.

| Version kind | Changed by | Mechanism | Effect on in-flight runs |
|---|---|---|---|
| Workflow definition version (what business owners publish) | Approved publish request | Row in `release_pointer(workflow_id, environment) → version_id`, written in one transaction with an audit record. Triggers read the pointer when they start a run and pass the definition digest as the run's input | None. A run is bound to the digest it started with. Rollback moves the pointer back for new runs |
| Interpreter and activity code (what the platform team ships) | Platform release | Temporal Worker Versioning: each build is a Worker Deployment Version; interpreter runs are **Pinned**, so they "complete on a single Worker Deployment Version"; new builds ramp by percentage ([versioning][temporal-wv]). The Temporal Worker Controller runs old and new versions side by side on Kubernetes and retires a version's pods when its runs drain ([controller][temporal-wc]) | None. Old runs finish on the old interpreter build |

Two refinements:

- **Staged rollout of a definition version (later).** The pointer can hold a primary and a candidate
  version with a percentage. The trigger chooses by a stable hash of the case key, so retries of the
  same email land on the same version. The candidate is promoted or withdrawn by another pointer move.
  Until it exists, production promotion is limited to `low` and `medium` workflows, then `high`, and
  `critical` waits for it.
- **Very long runs.** A case open for weeks keeps an old interpreter build alive. For runs past a
  threshold (proposed 30 days, [open question 7](../overview.md#open-questions)), the interpreter uses continue-as-new at a safe point
  (after a human decision) and moves to the current build, guarded by Temporal patching as the
  documentation requires for upgraded runs ([patching][temporal-patch]).

Promotion across environments copies the immutable definition and its evidence bundle by digest. No
rebuild happens between test and production, so the thing tested is byte-identical to the thing
promoted.

### Module versions

A workflow version pins exact module versions. A module owner releases a new module version
independently; workflows take it on their next publish, which re-runs their suite. The workflow's
approval covers every minor and patch release within the approved major version, so taking one
re-runs the suite and needs no new approval. A major version is one that adds an operation,
widens an operation's access, widens a subject-binding input, or changes egress hosts (`03` 4.1); it
needs a new approval for every workflow that moves to it. For emergencies
the owner can **revoke** a module version: the data gateway then refuses calls to it, and affected
runs fall into their human step (see failure modes). This gives the problem statement's "independent module
rollback" without silently changing what a running workflow calls, a failure seen in an earlier
internal product that attached tools at runtime ([design lessons](../../specs/design-lessons.md), "Tools, MCP and scoping").

### Advisory tests at the lowest tier

The problem statement says a re-test edit cannot promote until the suite passes. At `low` the
platform keeps tests advisory, because the first workflows will have few real examples per intent,
and a blocking pass rate on a small, young suite would stop routine wording changes while adding
little protection: `low` workflows have no `money_movement` action and every write still needs an
approval token. The deviation is bounded. The controls that stop harm (structure, evidence
integrity, injection) never become advisory. Each failure is explained in writing by someone other
than the maker and sealed into the evidence. The platform reports the override rate per workflow to
Model Risk (`04` 5.6). Model Risk can make `low` blocking by changing gate data, with no code change.
The gate's steps are data derived from the risk tier, so "advisory" and "blocking" are per-tier
settings (`04` 5.5 and 5.6 hold the gate data).

## Consequences

### Strongest counter-argument and our answer

**"Per-tier pools are coarse. A medium-risk HR workflow and a medium-risk payments workflow share a
process."** They share compute. Access stays per workflow: each activity call carries the workflow's own identity to
the data gateway, which enforces that workflow's module scopes; workers hold no credentials. A
department that needs compute segregation for regulatory reasons gets a dedicated pool, which the
design allows without a new architecture.

### What would change this decision

- The bank's Kubernetes platform cannot enforce default-deny egress per namespace. Then gateway
  enforcement moves to a service mesh or sidecar, at higher cost.
- Regulators require per-department compute segregation generally: then pools per department within
  tier.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Non-production and production clusters with the three environments; pools for `low` and `medium` (the only tiers promoted to production in phase 1); default-deny egress; payload codec and claim-check storage; pointer table with promote and rollback; exact module pins | `high` and `critical` pools; staged percentage rollout of definition versions; module revoke UI; dedicated department pools; continue-as-new upgrade for long cases |

## Sources

[openbao]: https://openbao.org/ecosystem/news/
[temporal-limits]: https://docs.temporal.io/cloud/limits
[temporal-patch]: https://docs.temporal.io/patching
[temporal-sec]: https://docs.temporal.io/self-hosted-guide/security
[temporal-wc]: https://docs.temporal.io/production-deployment/worker-deployments/kubernetes-controller
[temporal-wv]: https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning
