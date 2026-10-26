# Identity, trust and tenancy

Status: current, updated 2026-10-22: the team is the workspace, and that rule overrides anything below or in another doc that lets data cross teams. The decided design is [workflows and agents](../design/workflows/workflows-and-agents.md); decision records it does not settle remain options.

Every run acts for someone. Detail: [ADR-0005](decisions/identity-and-entitlement.md) (workflow identities,
delegation, approval tokens), [ADR-0013](decisions/auth-provider-seam.md) and
[sign-in library](../packages/ops_signin/overview.md) (human sign-in, step-up).

## The team is the workspace

A team in Ops AI is what a workspace is in other products: the one boundary for data. The rule:

| Rule | What it means |
|---|---|
| Every record belongs to exactly one team | Every agent, workflow, run, case, Human Task, file, document, knowledge base, tool module, mailbox, secret, task type and document type has a `team_id` that is never empty |
| A person belongs to one or more teams | Membership and a role per team. The console and every request act in one selected team at a time; switching team changes everything the person sees |
| Nothing crosses teams | No team reads, counts, decides, approves or uses another team's records. Another team's record answers 404, the same as one that does not exist |
| Approval stays in the run's team | A step a policy reserves for a person is decided by someone with the right role in the run's team. A tool policy names a role, never another team |
| Sharing is installing a copy | Ready-made tools, agents, workflows, task types and document types live in a catalog. A team installs one, which makes a copy in that team; later changes to the catalog entry reach the team only when it updates its copy |
| The tenant holds people, not work | The tenant (one per deployment by default) holds people, teams, memberships, sign-in policy and the catalog. It holds no work records |
| Background work acts in the record's team | A loop that claims work across teams (the worker, the mail listener, timers) reads only what it needs to find the record's team, then does the work in that team. It never returns another team's data to a person |

Other workspace products work the same way: every request carries one workspace, every query filters on it, and a
template is copied into a workspace rather than referenced across.

### Where the code still crosses teams

Each line is removed or changed by the card named; the boundary lock (`scripts/tests/test_team_boundary.py`) fails on
any new crossing: a table with a team column that is not team-owned or allows no team, a row policy that reads rows
with no team, or code that means "every team".

| Crossing | Where | Change |
|---|---|---|
| Tool modules with no team, and modules approved for another team's workflow | `services/tools-service/src/ops_tools/modules/directory.py:70` (`sees_module`, c-423), the no-team Platform tools module (c-433) | c-509: each team installs its own; keys are per team |
| A tool's approver is the module's owning team | `services/agents-service/src/ops_agents/api/routers/reviews.py:83`, `registry.approval_policy` (`op.approver_team or module.team_id`) | c-509: the approver is a role in the run's team |
| The dev header acts for every team at the request level | `ops_store.isolation.enter_caller` (reason `dev`) | c-509; inside agents-service the dev caller already acts in the one team its request names (c-507) |

Removed by c-507: rows with no team (every team-owned table's team column is `NOT NULL` and the read policy has no
null branch), task and case types shared across teams (each team holds its own copy, keyed by team), knowledge usage
counting other teams' agents, case reads with no team filter, and every agents-service code path meaning "every team".
Knowledge bases are held to their team by the database as well (kb_0011).

Account-level records, named in the lock with their reason: people, memberships, role assignments, API keys, sign-in
and membership audit entries (shown only to the account admin), the outboxes, and the background processes (the
built-in event workflows, their update notices, and the loops), which act in each record's team.

`isolation.tenant_wide` stays for background loops that claim across teams and seed data, each listed by reason in
`packages/ops_store/tests/test_isolation_sites.py`; each hands the work to the record's team and none returns data to
a request.

## Decisions

| Decision | Detail |
|---|---|
| Sign-in is a seam | The console calls one `AuthProvider` with `mock`, `oidc` and `firebase` adapters; a workspace's policy (methods, SSO domains, MFA, session length) comes from the API. Bank default: `oidc` against the bank's IdP, MFA required, invite only |
| Delegation per run | The adapter exchanges the caller's token for a short-lived delegation token: `sub` is who the work is for, `act` is who does it (the graph version), audience the tools gateway. OAuth token exchange (RFC 8693) where the IdP supports it |
| Process principals | Mailbox, schedule and webhook runs use a non-human principal owned by the team that owns the channel, with the entitlements that team approved. It can read and draft; it writes only with an approval token |
| Workload identity | Each service and worker pool has its own (SPIFFE or the platform's equivalent); service-to-service calls use mTLS or OIDC |
| Tool calls | Every tool call goes through tools-service, which asks OPA. A write needs an approval token bound to the input hash; money needs two approvers |
| Model calls | Every model call goes through models-service with the identity's own key and budget; workers hold no model keys ([ADR-0008](decisions/ai-gateway.md)) |
| Tenant and team | From the identity, never from a parameter or a run config |
| One auth dependency | Every service installs `ops_identity.fastapi.Auth` (`install_auth`) and its routes depend on `CurrentPrincipal` or `CurrentService`; no service reads tokens, keys or dev headers itself. `Auth.from_settings` picks dev or platform from `OPS_AUTH_MODE` alone |
| Calling service | An internal call's caller is its Ed25519 service token's subject (`service:<name>`), bound to that service's key; tools-service logs and decides on it and no body field names the caller |
| Trust facts stay out of model-visible text | Tenant, tier and identity come from the run context, never from the chat message |

## What each outbound call carries

| Call | Carries | Checked by |
|---|---|---|
| Tool read | Delegation token, `X-Lease-Generation` | tools-service: identity known, tool in the registry |
| Tool write | Delegation token, approval token, lease generation | OPA: token signed by the review service, `inputHash`, `tool`, `thread`, `step` match, not expired, two distinct approvers for money; tools-service: fence, dedupe |
| Model call | The identity's model key | models-service (planned); today a key-admission port admits every key and a thread budget pauses the thread ([human-in-the-loop.md](human-in-the-loop.md)) |

The access class (`read` or `write`) comes from the gateway's own registry; the caller never declares
it. A refusal lists every failed condition and reaches the model as a tool error, so the turn continues. Nine refusal
reasons are tested ([gateway-approval-token](../services/agents-service/experiments/gateway-approval-token.md)).

## Tenancy at rest

| Fact | Detail |
|---|---|
| Tables | `graph_threads`, `graph_runs`, `thread_events`, `review_decisions`, `review_approvals` (migration 0021) and `ops_checkpoints`, `ops_checkpoint_writes`, `ops_checkpoint_fences` (0004, 0008) carry `tenant_id`; existing rows are the dev tenant `local` |
| Policy | Each `ENABLE` and `FORCE ROW LEVEL SECURITY` with `tenant_id = current_setting('app.tenant_id', true)` for reads and writes; an unset tenant matches nothing |
| Tenant source | `ops_identity` enters each request's isolation context (`ops_store.isolation`: tenant, one team, scope) from the verified token or key, after the principal resolves; no service sets its own, and none is read from a body, header or path. Stores and the checkpointer read it per transaction; no repository takes a tenant argument. A path wider than one team names a reason (`isolation.tenant_wide`, `isolation.system_tx`), logged as `isolation.widen` and listed in `packages/ops_store/tests/test_isolation_sites.py` (c-409) |
| One tenant or many | `tenancy_mode` (`single`, the default, or `multi`) is the only difference: single refuses creating any tenant but the install's (`bootstrap_tenant_id`, else `local`), 409 `single_tenant` (`ops_platform/tenants.py`, `tests/test_tenancy_mode.py`). Still one tenant per deployment until c-272 closes them: `model_keys_tenant` (models-service's provider keys), `graph_tenant_id` (Microsoft Graph mail), and the 21 agents and 3 models tables with no `tenant_id` (c-334, c-413, c-416) |
| No tenant | A store call with no tenant raises `NoTenantError`; below the store, the tenant role with no `app.tenant_id` sees no row |
| Role | The compose database user is a superuser and bypasses RLS, so every tenant transaction runs `SET LOCAL ROLE ops_runtime_tenant`. A deployment must connect as a non-superuser role that owns no tables and may `SET ROLE` to `ops_runtime_tenant` and `ops_runtime_system` |
| Loops (answer a) | The sweeper and the timer poller claim before they know the tenant. They read it from the thread's row as `ops_runtime_system` (`BYPASSRLS`, `GraphStore.tenant_of`), then do the work in a new task that sets it, never on the loop's own context. Requests never run as that role; `tests/store/test_tenancy.py` holds the list of callers. The inbox drain runs inside a run and has its run's tenant |
| Checkpoints | One compiled graph serves every tenant: the saver takes the tenant from the same context variable when it opens each transaction. Team in the checkpoint key is `local`; team access is decided by the API before a thread is touched |
| Teams | Another team's thread, run, event or review in the same tenant answers 404, as another tenant's does, and lists show the acting team's only: the store reads through `team_visible` and the database holds the five run tables to the transaction's team (`{t}_isolation`, migration 0073, c-429). The reviewer is a person in the thread's own team. The dev header caller acts for every team of its tenant (reason `dev`) |
| External keys | Unique per `(tenant_id, external_key)`, so one tenant's key neither collides with nor reveals another's |
| Proven | `tests/store/test_tenancy.py` on PostgreSQL: each tenant counts only its own rows in every table with no tenant clause (turning RLS off on `graph_runs` fails it); a write naming another tenant is refused; one graph run by two tenants stores each checkpoint under its own tenant and B reads nothing of A's. `tests/api/test_platform_identity.py`: 404 across tenants, 403 with the owning team across teams, dev headers 401 in platform mode |
| Test databases | Every service's test conftest refuses `ops_runtime`, and any PostgreSQL database other than `OPS_TEST_DATABASE_URL`, before collection (`ops_service_kit.testdb`) |

## Approval and step-up token facts

The one table of token facts; other pages link here. From
[gateway-approval-token](../services/agents-service/experiments/gateway-approval-token.md) and
[approval-trust](../services/agents-service/experiments/approval-trust.md).

| Fact | Consequence |
|---|---|
| An approval token is bound to `{thread, step, tool, inputHash, approvers, exp}`; HS256, 15-minute TTL. Signing is `packages/ops_policy/src/ops_policy/tokens.py`; the binding is `ops_tools/tokens.py` | It covers one call; OPA verifies it with the review key |
| The input hash is SHA-256 of RFC 8785 canonical JSON (`ops_policy.input_hash`). `24` and `24.0` hash the same; key order does not matter; NaN is refused | Any second implementation must follow RFC 8785 or call ours, plus the NFC step below |
| Strings are normalised to NFC before hashing, an addition to RFC 8785 | A proxy that normalises text between approval and execution causes no refusal; a JCS library without NFC disagrees on decomposed text |
| Only approvals of the current input hash count | Any edit to the input after approval invalidates every approval of it |
| On resume the kernel hands the token to every gated call in the turn | A second call to the same tool with other arguments is refused on hash and step |
| The token travels in the decision, is checkpointed, and is journaled in the run input | It is bearer material at rest, bounded by its binding and TTL; the sweeper needs it to replay a crashed resume |
| An expired token is renewed from the recorded approvals of that exact call for up to 24 h ([durability-failure-and-audit.md](durability-failure-and-audit.md), Approval expiry) | A late resume or a sweeper recovery never asks the reviewer twice; the approval, not the token, bounds the window |
| Expiry is judged by the gateway's clock, sent to OPA as `now_ns` with every call, never by OPA's own clock. The gateway also writes its `gateway.rego` into OPA at start and answers 503 `policy_drift` on `/health` if OPA serves a different one | OPA runs in a container whose clock lagged the host by up to 104 s under load, and it then accepted a token 60 s past expiry; its file watch also missed a policy edit on a bind mount |
| A step that rewrites the draft after approval is refused at the gateway | Approve the last version of the draft |
| A step-up token is minted by `POST /v1/auth/step-up` for the caller: in dev auth by agents-service, signed with a key derived from the review key for that purpose only; under platform sign-in by platform-service after a password re-check, EdDSA under its session key with `typ` `step_up`, `email` the person and this service in `aud` | An approval token never passes as a step-up; a session token never passes as a step-up (`typ`), and a step-up never resolves as a session (`kind`) |
| agents-service accepts a platform step-up through the key set the shared Auth already caches, with no fetch of its own (`api/auth.py`, `verify_platform_step_up`) | The caller's own session token loaded the key; a step-up under a kid the cache does not hold is refused until the person's token refreshes under the new key |
| Every money decision verifies the step-up's signature, subject (the deciding person) and age (five minutes), and answers 422 `step_up_required` with the reason | Step-up authenticates the approver; it approves nothing by itself. A decision records a fingerprint of the step-up, never the token |

## Prototype shortcuts still in the code

The one list of trust shortcuts; other pages link here.

| Shortcut | Where | Production replacement |
|---|---|---|
| Dev auth: one fixed user in tenant `local`; `X-Dev-User` names a second reviewer; team from the `X-Team-Id` header | `ops_agents/api/auth.py` with `OPS_AUTH_MODE=dev`; refused by Settings outside `dev`. `OPS_AUTH_MODE=platform` resolves platform tokens and API keys through ops_identity and refuses the dev headers | Platform mode everywhere |
| HMAC (HS256) approval and step-up tokens: the verifier can also mint | `ops_policy.HmacSigner` behind the `Signer` interface, review key in Settings | A KMS `Signer` with an asymmetric key; only the Reviews code (`ops_hitl`) and the sign-in service can mint |
| The review key reaches OPA by a data write anyone who can reach port 8181 could overwrite | tools-service start-up | A signed OPA bundle |
| Internal routes accept any registered calling service | models-service's `/v1/models/*` routes take `CurrentService`; providers, keys and alias versions are what a person administers. TODO in `ops_models/app.py` | When the console gets a models admin page, those routes move to `CurrentPrincipal` with an admin role check; aliases, admit and calls stay service-only |
| Step-up from the demo password: agents-service's dev route, and platform-service's `POST /v1/auth/step-up`, which re-checks the one dev password | money decisions verify signature, subject and five-minute age | The identity provider re-authenticates (SSO, MFA) and platform-service mints |
| The requester check is partial. Workflow reviews refuse the requester (403, `hitl_facade.requester_of`); chat refuses self-approval only when `OPS_ALLOW_SELF_APPROVAL_IN_CHAT` is false (default true, owner decision pending), comparing display names; money refuses the same approver twice. `POST /v1/threads/{id}/approvals` has no requester check | `hitl_facade.py`, `routers/chat.py`, `routers/reviews.py` | The rule moves into the `ops_hitl` package with the requester taken from identity |
| Key budgets admit every key | `KeyAdmission` port in agents-service | A per-key ledger in models-service ([service-map.md](service-map.md)) |
| Chat approvals use `dev-approval:<id>` | `routers/chat.py` | Chat decide calls the approvals route; until then turning the gateway on refuses chat writes |

## Open

Whether the bank's IdP can issue a delegation token with an `act` claim is untested (overview open question 6). If it
cannot, the gateway mints internal delegation tokens after authenticating both parties, which concentrates trust in
the gateway and needs Security's sign-off.
