# Platform service: identity, tenancy, members and keys

Status: expectation spec for the first slice, not decided beyond what `identity-and-tenancy.md` already
records. Refines `governance-and-admin.md` (teams, members, audit, keys) and `sign-in-and-sessions.md`
(the AuthProvider seam) into the service every other service depends on for *who is calling and for
which tenant*. Built test-first: the use cases in section 7 are the acceptance bar; code follows them.

## 1 Why now

Every service resolves identity through a dev stub: one fixed user, team from an `X-Team-Id` header,
`runContext.sub` asserted by the caller (`identity-and-tenancy.md`, prototype shortcuts). Nothing checks
that a caller belongs to the team it names, and the only tables with row-level security are the
checkpointer's. Agents, workflows, threads, reviews and events are tenant data with no tenant guard.

## 2 Scope of the first slice

| In | Out (later slices) |
|---|---|
| Tenants, teams, users, members and roles | OIDC and Firebase adapters, MFA, SSO by domain |
| Sessions in `dev` mode, a platform-issued identity token and a rotating refresh token | IdP token exchange (`POST /v1/auth/exchange` taking an OIDC or Firebase id_token plus an optional invite code), forgot and reset, MFA enrol and verify, policy-driven session length and idle limits, device session list and revoke, step-up moving here from agents-service |
| API keys per team with scopes | Notifications, webhooks, usage, search, run-as principals |
| Audit entries for every write | SPIFFE workload identity (service token stays) |
| `ops_identity` package every service uses to resolve the caller | Console sign-in pages on the real API (mock adapter stays) |

## 3 Entities

| Entity | Fields | Rules |
|---|---|---|
| `Tenant` | `id`, `name`, `status` | The organisation. One database, RLS by `tenant_id`; a deployment may still run one tenant |
| `Team` | `id`, `tenant_id`, `name`, `owner_groups[]`, `scope` (`all`, `owned`) | `governance-and-admin.md` 4.1 |
| `User` | `id`, `tenant_id`, `email` (unique per tenant), `name`, `status` | A person; never a unit of authorisation on its own |
| `Member` | `user_id`, `team_id`, `role` (`admin`, `builder`, `approver`, `viewer`), `status` (`active`, `invited`) | 4.2; a person can be in several teams; a team always keeps at least one active `admin` |
| `ApiKey` | `id`, `tenant_id`, `team_id`, `name`, `prefix`, `secret_hash`, `scopes[]` (`read`, `write`), `created_by`, `last_used_at`, `revoked_at` | Secret shown once at creation, stored hashed, looked up by prefix; bound to one team |
| `Session` | `id`, `user_id`, `tenant_id`, `expires_at`, `revoked_at`, `auth_method`, `refresh_hash`, `last_seen_at` | Issued at sign-in with an opaque refresh token (stored hashed, rotated on every refresh); sign-out revokes; `last_seen_at` is what a later idle limit reads |
| `AuditEntry` | `id`, `tenant_id`, `team_id` (null for tenant-level events such as sign-in), `actor` (principal), `action`, `target_kind`, `target_id`, `request_id`, `at`, `detail` | Append only; written in the same transaction as the write it records |

## 4 The identity contract

`Principal` is what every service receives after `ops_identity` resolves a request:

| Field | Source |
|---|---|
| `kind` | `person`, `api_key` or `service` |
| `sub`, `email`, `name` | The user, the key's creator, or the service name |
| `tenant_id` | From the token or key, never from a header, body or path |
| `team_id` | The one team this request acts in: `X-Team-Id` selects among `team_ids` from the token and grants nothing on its own; absent header with one team selects it; a team not in the set is 403 `team_forbidden` |
| `team_ids`, `roles` (per team) | From membership at token issue, refreshed on each session renewal |
| `scopes` | API keys only; a `read` key is refused on every write route with 403 `scope_required` |
| `auth_method` | `dev`, `session`, `api_key`, `service` |

Platform-service is an identity service, not a gateway: it is the only issuer of tokens and routes nothing. Tokens
are signed asymmetrically (Ed25519, or ES256 where a deployment's HSM requires it): platform-service holds the private
key, from the environment (your secrets manager) with a generated key in dev mode only, and publishes the public key at
`GET /.well-known/jwks.json` (public, cacheable, keyed by `kid` for rotation). Every other service verifies locally
through `ops_identity`: signature, `exp`, `tenant_id`, `team_ids`, `roles`; no call to platform-service on the request
path, and a service holding only the public key cannot mint a token that passes.

Tokens carry `aud` naming the service they are for; a token for one service is refused by every other, since local verification would otherwise let any service replay a received token everywhere. Clients that can only send `Authorization: Bearer` (MCP clients, pasted URLs) may present an API key as `Bearer ok_…`; `ops_identity` classifies by prefix.

Resolution order in `ops_identity`: `Authorization: Bearer <platform token>` (verified against the cached JWKS; an
unknown `kid` refetches once, then 401), then `X-API-Key: ok_<id>.<secret>` (the one exception: verified by
platform-service `POST /v1/auth/introspect` on the internal mount, cached briefly so revocation is near-immediate),
then the service token on internal mounts only (a separate key from user tokens, so a service can never mint a user token; a service call carries the tenant as a claim in its own token or forwards the caller's token, never a header), then dev mode (`OPS_AUTH_MODE=dev`: fixed user, `X-Dev-User`,
refused outside `dev` by Settings). Token claims: `sub`, `tenant_id`, `team_ids`, `roles`, `kind`, `auth_method`, `aud`, `exp`, plus `amr` and `auth_time` reserved for the MFA and step-up slices so no service has to change its verifier later. Token TTL is 15 minutes; a renewal uses the refresh token (`POST /v1/auth/refresh`), never the expired token itself, while the 8-hour session lives (a per-tenant sign-in policy replaces the fixed 8 hours in a later slice). Accepting an invite, a role change and a team switch each return a fresh token at once, so a new membership never waits out the old token's TTL; sign-out or
removal takes effect at platform-service at once and at other services when the token expires. A pushed revocation
list is a later option if 15 minutes proves too long. The console calls each service's own URL, or a plain reverse
proxy with no auth logic. `agents-service` keeps its `principal` dependency name and swaps the body for
`ops_identity.principal`; `tools-service` takes `runContext.sub` from the token, not the caller.

## 5 Isolation rules (each one has a use case that fails without it)

| # | Rule | Lesson it comes from |
|---|---|---|
| I1 | Tenant and team come from the identity. A request body, query or path never names them, and a model-supplied id never widens a write | A system tool preferred `args.customerId` over the conversation's customer and could flip a compliance flag on any customer in the workspace; a user-token path fell back to a raw workspace header when the token carried none |
| I2 | Every tenant-owned table carries `tenant_id` and `team_id`; RLS forces `tenant_id = current_setting('app.tenant_id')` with `SET LOCAL ROLE`, as the checkpointer does. A record in another tenant is 404 (no existence leak); a record in another team of the same tenant is 403 with the owning team's id and name. API keys answer 404 across teams, since confirming a key exists to another team helps no one | Checkpointer RLS proof in `identity-and-tenancy.md`; `governance-and-admin.md` 5.1.3 |
| I3 | Anonymous callers get 401 on every route except health, sign-in and invite accept. No public write route exists | A product shipped a default endpoint that accepted anonymous writes because the URL was treated as the secret |
| I4 | API keys: created only by an `admin` of the team the key is bound to; the secret appears once; `last_used_at` updates on use; revoke is immediate; a key never outlives its team | A gateway route minted keys for any workspace from a body field; the fix enforced that the named user was that workspace's owner |
| I5 | Request models reject unknown fields and validate id formats | Strict DTOs with `forbidNonWhitelisted` are what catches a caller sending a tenant id "for convenience" |
| I6 | The last active `admin` of a team cannot be demoted or removed; the operation is skipped in a `BulkResult` with a reason | `governance-and-admin.md` G5 |
| I7 | Every write produces an `AuditEntry` in the same transaction with the actor, request id and target; admins read their team's entries, Platform reads all | Audit was bolted on after the fact elsewhere and missed the writes that mattered |
| I8 | Internal routes (`introspect`, timer fire) live on a separate mount guarded by the service token and are never exposed by the public port | Admin API on an internal port is what kept one platform's admin surface off the public host |
| I9 | API key scopes are enforced by `ops_identity` from the HTTP method, not opt-in per route: a `read` key is refused on every non-GET route. uc-024 walks every non-GET operation in `openapi.json` with a read key and expects 403 | A platform stored read, write and admin permissions on keys and nothing enforced them: no route checked the permission list |
| I10 | Removing or suspending a member disables every key they created and revokes their sessions | A platform bound the key's principal to its creator and never rechecked membership, so a removed person's keys kept working |
| I11 | Key hashes compare in constant time | A platform compared key hashes with `!==` |
| I12 | Secret and key material never reaches a log, including prefixes and lengths on failures | A product logged the first four characters and the length of the presented secret on every failed verify |
| I13 | Service tokens are signed with their own key, carry the tenant as a claim, and are accepted only on internal mounts | A platform signed service and user tokens with one HS256 secret and took the service call's workspace from a header, so any service could mint a user token for any workspace |
| I14 | Tokens carry `aud`; a service refuses a token issued for another service | Local verification everywhere turns every received token into a replayable credential without it |

## 6 API

| # | Operation | Request | Response | Errors |
|---|---|---|---|---|
| P1 | `POST /v1/auth/sign-in` | `email`, `password` (dev mode: the fixed demo password) | `Session` + platform token | 401 |
| P2 | `GET /v1/auth/session` | | `Principal` for the token | 401 |
| P3 | `POST /v1/auth/sign-out` | | 204; revokes the session and its refresh token | |
| P3a | `POST /v1/auth/refresh` | refresh token | new platform token and rotated refresh token | 401 on reuse of a rotated token (the session is revoked) |
| P4 | `POST /v1/auth/introspect` (internal) | `api_key` | `Principal` or 401 | service token required |
| P4a | `GET /.well-known/jwks.json` | | public keys by `kid` | public, cacheable |
| P5 | `GET /v1/me` | | user, teams, roles | |
| P6 | `GET /v1/teams` | | `Team[]` the caller belongs to (`governance-and-admin.md` G1) | |
| P7 | `GET /v1/settings/members` | filters `role`, `status` | `ListResult<Member>` for the current team (G3) | |
| P8 | `POST /v1/settings/members/invite` | `emails[]`, `role` | `BulkResult` (G4); invited members hold no session until they accept | admin only |
| P9 | `POST /v1/settings/members/role` | `ids[]`, `role` | `BulkResult`, last admin skipped (G5) | admin only |
| P10 | `POST /v1/settings/members/delete` | `ids[]` | `BulkResult`, last admin skipped (G6) | admin only |
| P11 | `GET /v1/api-keys`, `POST /v1/api-keys`, `POST /v1/api-keys/{id}/revoke` | `name`, `scopes[]` | key list without secrets; create returns the secret once | admin only |
| P13 | `GET /v1/invites/{token}`, `POST /v1/invites/{token}/accept` | | the invite's tenant, team and role; accept creates the member and returns a session and token | public read; accept checks the invite's expiry and, when the tenant sets allowed domains, the email domain |
| P12 | `GET /v1/audit` | filters `action`, `actor`, `target_kind`, time range | `ListResult<AuditEntry>` for the current team | admin only |

`ops_identity` verify tests: a token signed with another key is 401; an unknown `kid` refetches the JWKS once, then
401; a service holding only the public key cannot mint a token that passes.

Every route typed from the first commit: operationId, tag `platform`, request and response models, the
error envelope, listed in a committed `openapi.json` with an allowlist of untyped routes that starts
empty and may not grow. `/v1/health` and the JWKS route are the only unauthenticated reads.

## 7 Use cases: the acceptance bar

| Id | Name | Checks | Fails without |
|---|---|---|---|
| uc-021 | Sign in, session, refresh, sign out | dev sign-in returns a token and a refresh token; `/v1/auth/session` resolves it; a token past its TTL is 401 and refresh returns a fresh one; reusing a rotated refresh token is 401 and ends the session; after sign-out both are 401 | the session store, I-refresh rotation |
| uc-022 | Team scoping | member of team A lists agents and sees only A's; `X-Team-Id: B` without membership is 403 `team_forbidden`; A's agent opened by id from another tenant is 404; from another team of the same tenant is 403 naming the owner team | I1, I2 |
| uc-023 | Members and roles | invite two emails; change one to `approver`; demoting the only admin is skipped with a reason; removing a member revokes their sessions and disables keys they created; accepting an invite returns a token that already carries the new team | I6, I10, P8 to P10, P13 |
| uc-024 | API keys | create returns the secret once and the list never shows it; the key calls `GET /v1/agents` on agents-service and `last_used_at` moves; a `read` key is refused on every non-GET operation in `openapi.json` with `scope_required`; the key presented as `Bearer ok_…` works the same; a revoked key is 401; a key from team B is refused on team A's records | I4, the `ops_identity` key path |
| uc-025 | Audit | every write in uc-023 and uc-024 leaves one entry with actor, request id and target; a viewer reading `/v1/audit` is 403 | I7 |
| uc-026 | Anonymous and dev boundary | every route but health, JWKS, sign-in and invite accept is 401 without credentials; `X-Dev-User` is ignored when `OPS_AUTH_MODE` is not `dev`; a token with another service's `aud` is 401; a service token presented on the public mount is 401 | I3, I8, I13, I14 |

Each use case runs at the api layer through the use-case runner against platform-service and
agents-service together; uc-022 and uc-024 are end to end through the real `ops_identity` seam, not a
hand-built principal. The pass bar for the slice is all six green and the existing uc-001 to uc-020
unchanged.

## 8 Build order and consumers

1. `services/platform-service`: skeleton from `python-service-skeleton.md`, own alembic chain, settings on
   `ops_service_kit`, migrations for section 3, RLS as the checkpointer does it.
2. Store and service layer, then typed routes P1 to P12.
3. `packages/ops_identity`: `principal` dependency, token verify, key introspection with a cache, dev mode.
4. `agents-service` and `tools-service` adopt `ops_identity`; dev mode behaviour unchanged, so every
   existing use case still passes; `graph_threads`, `graph_runs`, reviews and events gain `tenant_id`
   and RLS in agents-service's own migration.
5. Use cases uc-021 to uc-026, registered in `docs/usecases/README.md`.
6. Make: `make -C services/platform-service up|verify|migrate`, a row in `make health`, port
   `OPS_PLATFORM_PORT` default 8710 in `make/env.mk`, `OPS_PLATFORM_URL` for the other services.
7. Console: unchanged in this slice; the mock AuthProvider keeps working. The `platform` adapter is the
   next slice, through the generated SDK.

## 9 Open decisions for the owner

| Question | Default taken until decided |
|---|---|
| Name for the organisation level: tenant, workspace or organisation | `tenant` in code and tables; the console may label it Organisation. For readers used to a single "workspace" level: the unit that roles and keys bind to is this spec's Team, and a single owner field maps to the Team's protected last `admin` |
| Platform token TTL and renewal | 15 minutes, renewed by `GET /v1/auth/session` while the session lives (8 hours); decided by the owner 2026-10-11 together with asymmetric signing and no gateway |
| API key format | `ok_<id>.<secret>`, 32 random bytes, SHA-256 at rest |
| Whether a `viewer` may create API keys for themselves | No; keys are an admin action |
| Where step-up is minted | Stays `POST /v1/auth/step-up` on agents-service in this slice; moves here with the MFA slice, carrying `auth_time` |
| Console `Session.role` is one role per workspace; `Principal.roles` is per team | The console adapter picks the current team's role; the per-team model stands (`governance-and-admin.md` open question 1) |
| Which services a person's token names in `aud` | Every user-facing service, from `OPS_PLATFORM_AUDIENCES`: the console holds one token, not one per service. I14 still refuses a token at any service it does not name, and binds service tokens and narrowed tokens to one service |
