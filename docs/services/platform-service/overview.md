# platform-service

Status: first slice and sign-in providers (c-188) built, checked 2026-10-17. `services/platform-service` (`ops_platform`), public app on :8710 and
internal app on :8711 (localhost only), with its own migration chain (`alembic_version_platform`). `make up` starts it
and lists it in `make health`. Tests: `services/platform-service/tests`; use cases uc-021, uc-023, uc-025, uc-026.
Design: this page, service map row `platform-service`.

## What it does

It is the identity issuer and nothing else: it owns tenants, teams, users, members, sessions, invites, API keys and
the audit log, and it is the only service that mints identity tokens. It routes no other service's traffic. Every
other service verifies callers locally with `packages/ops_identity`: platform tokens against the published key set,
API keys through introspection on the internal app, service tokens on internal routes only.

| Credential | Shape | Verified by |
|---|---|---|
| Platform token | EdDSA JWT, 15 minutes, `aud` listing every user-facing service, claims per spec section 4 | Each service, against `GET /.well-known/jwks.json` |
| Refresh token | `<session id>.<secret>`, rotated on every refresh; a reused one ends the session | platform-service |
| API key | `ok_<id>.<secret>`, secret shown once, SHA-256 at rest, optional expiry, optional target (one agent or workflow, c-246) | platform-service, via `POST /v1/auth/introspect` |
| Service token | EdDSA JWT, 60 seconds, signed with the calling service's own key, `sub` bound to that key | The callee's `ServiceAuth` |
| Step-up token | EdDSA JWT, 5 minutes, same key and `aud` as the platform token, `kind` and `typ` `step_up`, `sub` and `email` the person who re-entered their password (`POST /v1/auth/step-up`) or signed in again at their SSO provider (`POST /v1/auth/step-up/sso/*`), audited as `auth.step_up` with the method | agents-service `require_step_up`, against the cached key set; refused as a session by every service |

## Routes

| Mount | Operations |
|---|---|
| Public :8710 | `GET /v1/health`, `GET /.well-known/jwks.json`, `POST /v1/auth/sign-in`, `GET /v1/auth/session`, `POST /v1/auth/refresh`, `POST /v1/auth/step-up`, `POST /v1/auth/sign-out`, `GET /v1/me`, `GET /v1/teams`, `GET /v1/settings/members`, `POST /v1/settings/members/invite`, `.../role`, `.../delete`, `GET /v1/api-keys`, `POST /v1/api-keys`, `POST /v1/api-keys/{id}/revoke`, `GET /v1/api-key-summaries` (service token with `settings:view`: every team's keys and their targets, for the Channels list), `GET /v1/audit`, `GET /v1/invites/{token}`, `POST /v1/invites/{token}/accept`, `POST /v1/auth/options`, `POST /v1/auth/sso/start`, `GET /v1/auth/oidc/callback`, `POST /v1/auth/saml/acs`, `GET /v1/auth/saml/metadata`, `POST /v1/auth/sso/complete`, `POST /v1/auth/step-up/sso/start`, `.../complete`, `POST /v1/auth/password/forgot`, `POST /v1/auth/password/reset`, `GET /v1/settings/sign-in/providers`, `PUT`/`DELETE /v1/settings/sign-in/providers/{id}`, `POST /v1/settings/sign-in/domains/{domain}/verify`, `GET /v1/settings/sign-in/secret-names`, `GET`/`POST /v1/settings/teams`, `PATCH /v1/settings/teams/{id}`, `POST /v1/settings/teams/{id}/archive`, `.../restore`, `GET /v1/settings/members/options`, `POST /v1/access/check`, `GET /v1/me/why`, `GET /v1/roles`, `GET /v1/roles/{id}`, `GET /v1/people/{id}/permissions` |
| Internal :8711 | `POST /v1/auth/introspect` (service token, no tenant claim) |

Every operation is typed in `services/platform-service/openapi.json`; `make -C services/platform-service
openapi-check` fails on drift.

## Settings

| Setting | Default | Notes |
|---|---|---|
| `OPS_PLATFORM_PORT`, `OPS_PLATFORM_INTERNAL_PORT` | 8710, 8711 | `make/env.mk`; ISOLATED=1 adds 1000 |
| `OPS_PLATFORM_URL` | `http://127.0.0.1:$(OPS_PLATFORM_PORT)` | Where other services fetch the key set |
| `OPS_PLATFORM_SIGNING_KEY`, `OPS_PLATFORM_SIGNING_KID` | unset, `platform-1` | Required outside dev; dev derives a key from a public seed under kid `platform-dev` |
| `OPS_PLATFORM_AUDIENCES` | every user-facing service | The `aud` of a person's token |
| `OPS_PLATFORM_TOKEN_TTL_SECONDS` | 900 | Use cases shorten it to watch a token expire |
| `OPS_PLATFORM_DEMO_PASSWORD` | `northfield-demo` | Dev only, for a person with no stored password; unset outside dev |
| `OPS_PLATFORM_PUBLIC_URL`, `OPS_CONSOLE_URL` | unset | platform-service's public origin (the OIDC redirect URI `/v1/auth/oidc/callback`, the SAML consumer URL `/v1/auth/saml/acs`, the SAML entity id `/v1/auth/saml`) and the console's origin (`/sso/callback`, `/reset-password/<token>`); unset, SSO and reset answer 503 |
| `OPS_SAML_SP_KEY`, `OPS_SAML_SP_CERTIFICATE` | unset | The SAML service provider's key pair, PEM (c-197): signs requests for a provider with `signRequests`, decrypts assertions encrypted to the certificate, and the certificate is published at `/v1/auth/saml/metadata`; unset, a provider cannot ask for either (400 `sp_key_missing`) |
| `OPS_SIGNIN_SECRETS` | `{}` | JSON name to secret; an OIDC provider's `clientSecretRef` names one |
| `OPS_PASSWORD_HASH_ITERATIONS`, `OPS_PASSWORD_MIN_LENGTH` | 600000, 12 | PBKDF2-SHA256 work factor (a lower stored count is rehashed at the next sign-in) and the shortest password a reset or invite accepts |
| `OPS_SIGNIN_FLOW_SECONDS`, `OPS_PASSWORD_RESET_SECONDS` | 600, 3600 | How long an SSO round trip and a reset link live |
| `OPS_MAIL_PROVIDER` and its settings | `none` | Reset links go out through `packages/ops_email`; `none` makes forgot answer 503 `mail_not_configured` |
| `OPS_PLATFORM_SEED_FILE` | `services/platform-service/tests/fixtures/people.json` | Dev seed: `team_ops` with an admin, a builder and an approver |
| `OPS_SERVICE_SIGNING_KEY`, `OPS_SERVICE_SIGNING_KID` | unset, `svc-dev` | A calling service's own key; required outside dev |
| `OPS_SERVICE_PUBLIC_KEYS` | `{}` | `{kid: {"service", "x"}}`: the services the internal app trusts |

## Policies

The workspace's rules, read and changed at `GET /v1/policies`, `GET /v1/policies/{key}` and `PUT /v1/policies/{key}`
(Govern › Policies in the console). They are defined once in `packages/ops_access/src/ops_access/policies.py`, which
this table is generated from. A per-team policy holds a value per team; a team with none set takes the default.

| Key | Name | Scope | Default | What it does |
|---|---|---|---|---|
| `requesterMayDecide` | Requester may decide | workspace | True | The person who asked for a decision may also make it. Off: someone else has to decide. |
| `extractionFloor` | Extraction confidence floor | workspace | 0.8 | The lowest confidence an Extract from file step may accept; no step can ask for less. |
| `stepUp` | Step-up on every approval | workspace | False | Every approver confirms their sign-in again before deciding. Off: only operations that ask for it. |
| `publishReview` | Publish reviews | per team | off in every team | Which of a team's publishes wait for review: always, major changes only (the default), or never. |
| `chatThreadsOwnerOnly` | Private chat threads | workspace | True | Each chat thread is read only by the person who started it. Off: the team's admins read them too. |
| `memoryRetentionDays` | Memory retention | workspace | None | How long agents keep what they remember about each person. Unset: kept until the person removes it. |
| `reviewSlaHours` | Review deadline | workspace | 8 | How long a publish review may wait, in wall-clock hours, before it shows as overdue. |
| `toolWritesNeedApproval` | Approve every tool write | per team | off in every team | Every tool write by the team waits for a person's approval, including the ones a tool lets run at once. |
| `aiSteps` | AI steps in workflows | per team | off in every team | The team's workflows may use AI steps: Classify, Summarise, Extract from text, Draft. Off until turned on. |
| `taskAssist` | Task assist | per team | off in every team | A typed task opens with AI help: its question, a summary, doubtful fields and a suggestion. Off until on. |
| `checkBeforeSend` | Check before sending | per team | off in every team | Every write the team sends is checked against its sending policy first; a failure waits for a person. |
| `pageImages` | Page images to the model | per team | off in every team | Document types in the team may show the model the page image of a scan or a doubtful field. Off until on. |
| `aiStepsMaskPersonalData` | Mask personal data in AI steps | per team | off in every team | People see SSNs, card and account numbers, emails and phones masked in AI steps' output and in document type examples. A team may turn it off. |
| `securityTeamAddsSecrets` | Only Security adds secrets | workspace | False | Only the security team adds secrets. Off: builders add and use their own team's secrets. |

Three are off until a team turns them on: `aiSteps`, `taskAssist` and `checkBeforeSend`. agents-service and
tools-service read them per team when a step runs, a task opens or a write is about to be sent.

## Sign-in

A workspace's methods are rows in `signin_providers`, set by Security team admins at `/v1/settings/sign-in/providers`:
`password`, `oidc` (authorization code with PKCE) and `saml` (SP-initiated). A workspace with no enabled row signs in
by password, so turning off its only SSO provider never locks everyone out. A `signin_domains` row is a workspace's claim on an
email domain for one provider, with a token: it routes sign-in and makes people only once `POST
/v1/settings/sign-in/domains/{domain}/verify` has seen `ops-ai-verify=<token>` in the domain's TXT records (c-195,
migration 0017; resolvers from `OPS_SIGNIN_DNS_SERVERS`). One workspace can hold a domain verified, and another's
pending claim blocks nobody. Settings → Sign-in in the console sets providers and verifies domains. The
console asks `POST /v1/auth/options` for the typed email and shows those methods. Wrong passwords at sign-in and
step-up count together per person in `signin_lockouts` (migration 0019, c-196): five in fifteen minutes lock both for
fifteen (429 `signin_locked` with `Retry-After`), a right password clears the count and a used reset link ends the
lock; one person is sent at most three reset links an hour. The limits are `OPS_SIGNIN_MAX_FAILURES`,
`OPS_SIGNIN_FAILURE_WINDOW_SECONDS`, `OPS_SIGNIN_LOCKOUT_SECONDS`, `OPS_PASSWORD_RESET_MAX_PER_WINDOW` and
`OPS_PASSWORD_RESET_WINDOW_SECONDS`.

| Step | What happens |
|---|---|
| Start | `POST /v1/auth/sso/start` finds the provider by the email's domain, keeps state, nonce, PKCE verifier or SAML request id in `signin_flows`, and returns the provider URL and a `flowKey` |
| Answer | The provider returns to `/v1/auth/oidc/callback` or `/v1/auth/saml/acs`; `packages/ops_signin` checks the answer, the person is found by provider subject, then by email, then made in the provider's first sign-in team with its role (default `chat_user`), only for an email on the provider's domains; the browser goes to the console's `/sso/callback?code=` (303) |
| Complete | `POST /v1/auth/sso/complete` takes the code and the starting browser's `flowKey`, once, and issues a session whose `authMethod` is `oidc` or `saml` and whose `provider_id` is kept |
| Step-up | A password session re-enters its password; an SSO session goes back to its own provider with `prompt=login` or `ForceAuthn`, and the answer must be the same person with a fresh login |

Local identity providers for tests and the dev stack: `uv run python -m ops_signin.fake_idp --port 8790`.

## Teams

Workspace admins, people with the Admin role in every team (`*`; the dev seed's Wanjiru Kamau), create a team with its
first admin, rename it and archive or restore it at `/v1/settings/teams` (c-198). A name is unique in the workspace in any
case (`teams.name_key`). An archived team keeps what it owns, leaves its members' next tokens and `GET /v1/teams`, gives
its members no rights there and takes no new invitations; the Security team cannot be archived. Team admins manage
members and roles on `/v1/settings/members/*` as before.

## Access checks

An admin checks one action for one person at `POST /v1/access/check` (c-150): the answer comes from the same `can()` the
services run, with the workspace's policies, and names the person checked when it refuses ("Maya asked for this", not
"You asked for this"). Each check is written to the audit log as kind `checked`, read as "Checked <person>'s access to
<action> on <area>". `GET /v1/me/why` answers the signed-in person's own locked button: the roles that grant the action
and who in the team can give roles; it is not audited. `GET /v1/settings/members/options` lists the team's active people
as picker choices by email (a Human Task sent back to a person), searched in the query, for anyone who may decide reviews.

## Operations

| Topic | Detail |
|---|---|
| Database role | The service connects as a login role that owns no table and is a member of `ops_platform_tenant`. Every transaction switches to that role; row-level security is forced on every table |
| Pre-tenant lookups | Sign-in by email, a session by id, a key by prefix and an invite by token hash (migration 0004), and an email domain, a sign-in flow by state or handoff hash and a reset by token hash (migration 0010) are SECURITY DEFINER functions owned by the NOLOGIN role `ops_platform_lookup`, whose only right is SELECT through SELECT-only policies |
| Migrator rights | Migration 0004 runs `ALTER FUNCTION … OWNER TO ops_platform_lookup`. The migrating role must be a superuser, or have CREATE on the schema and be a member of `ops_platform_lookup`. Compose's user is a superuser; a managed database usually needs the grant first |
| Key rotation | Publish the new public key beside the old one in the key set, switch `OPS_PLATFORM_SIGNING_KEY` and its kid, and drop the old key after the token TTL. Verifiers refetch once on an unknown kid |
| Sign-out reach | platform-service refuses a signed-out session at once; other services accept its token until it expires (15 minutes) |

## Gotchas

| Topic | Detail |
|---|---|
| Superuser hides RLS faults | The compose user bypasses row-level security, so `tests/test_least_privilege.py` runs the flows as a role that owns nothing; without migration 0004 they fail there and pass everywhere else |
| Definer functions and temp tables | Postgres searches a session's temporary schema first unless a function names `pg_temp` in its search_path, so a temp `users` table could shadow what a lookup reads. The lookups pin `pg_catalog, public, pg_temp` and qualify every table (migration 0005) |
| Foreign keys ignore RLS | A single-column reference let a tenant's row point at another tenant's team; every reference carries `tenant_id` (migration 0002) |
| String annotations and FastAPI | `api/app.py` has no `from __future__ import annotations`: its routes depend on functions local to the factory |
| Test teams | Fixtures create teams with scope `owned`; a scope `all` team reads the whole tenant and would hide team scoping |

## Not built yet

| Item | Where it goes |
|---|---|
| agents-service and tools-service resolving callers through `ops_identity`, with RLS on their tables (uc-022, uc-024) | The adoption card |
| MFA; a limit per client address on sign-in | Later slices of [sign-in library](../../packages/ops_signin/overview.md) |
| SAML single logout and identity-provider-initiated sign-in | c-217 (proposed) |
| Sending invitations by mail | The notifications slice; today the admin shares the link from the invite response |
| A pushed revocation list | Only if 15 minutes of reach after sign-out proves too long |
