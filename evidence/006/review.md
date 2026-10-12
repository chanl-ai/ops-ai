# c-006 independent review

One entry per commit, by a reviewer that did not build it. Each check ran on a clean `git archive HEAD` export
against a private database (`ops_review_e556`); the working tree was never edited.

## 4821822: one OpenAPI gate and response envelope in ops_service_kit

- Check: `make python-verify` on the HEAD 3745fcb export. Exit 0; agents-service 189 passed; `check_openapi.py`
  reports 60 operations, 0 untyped.
- Spec rule: platform-service.md:111-113 (every route typed, error envelope, committed openapi.json, untyped allowlist
  starts empty and may not grow).
- Verdict: accept.
- Notes: `committed_count` reads `HEAD:`, so "may not grow" only holds before commit; on a PR, or an export with no
  git, a committed growth passes. Compare against the merge-base with origin/main. This behaviour predates the commit.
  `contract.typed` and `openapi.typed` are two functions that treat 204 and SSE differently; there should be one.

## 81ae072: Ed25519 tokens with kid and audience

- Check: ops_policy 52 passed; test_ed25519 9 passed. Replacing `if audience is not None` with `if False` fails
  test_a_token_for_another_audience_is_refused, so that test can fail.
- Spec rule: I14, platform-service.md:87 (a service refuses a token issued for another service); I13 at :86.
- Verdict: reject.
- Defect: `verify(..., audience: str | None = None)` checks `aud` only when the caller passes it, so an EdDSA verify
  that omits it accepts a token for any service. Make audience required for Ed25519 verifiers, or bind it to the
  verifier. I13's tenant claim and internal-mount rule are not this primitive's job; they belong in ops_identity.

## 3745fcb: identity tables under forced row-level security, audited writes

- Check: platform-service verify 6 passed, inside the green python-verify.
- Spec rule: I2, platform-service.md:75 (tenant boundary); I7, :80 (audit entry per write).
- Verdict: reject.
- Defect 1: proven on the review database. Inside `tenant_tx(A)`, a `members` row with tenant_id=A and team_id set to
  tenant B's team inserts. RLS WITH CHECK reads only tenant_id, and FK checks ignore RLS. The same hole is on
  `api_keys.team_id`, `members.user_id` and `sessions.user_id`; `audit_entries.team_id` has no FK. Fix: composite FKs
  `(tenant_id, team_id)` to `teams(tenant_id, id)`, likewise for users, plus a test that the insert fails.
- Defect 2: tables.py says audit is append-only, but the migration grants UPDATE and DELETE on `audit_entries` to
  `ops_platform_tenant`; the probe deleted an audit row as tenant A (rowcount 1). Grant SELECT and INSERT only.

## Second reviewer: 25781ce to d9b2684

Each check ran on a clean `git archive` export of `d9b2684` against private databases (`ops_review_c006` for the
suites, `ops_probe_c006` migrated by platform-service's own chain for the probes); the working tree was never edited.
`make python-verify` there: platform-service 67 passed (lint, pyright, OpenAPI gate); ops_identity and ops_policy
green; agents-service 199 passed and 2 failed in OPA-backed gateway tests ("approval token is not signed by the
review service"), both passing on a rerun of the same export, so a shared-OPA flake outside this card. Use cases on
the same export: uc-021 8, uc-023 6, uc-025 5, uc-026 4 checks, all passing.

## 25781ce: bound audience, tenant-scoped foreign keys, append-only audit

- Check: probes as `ops_platform_tenant` in tenant A: a member row pointing at tenant B's team, and one at tenant B's
  user, both refused with `ForeignKeyViolationError`; DELETE, UPDATE and TRUNCATE on `audit_entries` all refused
  with `InsufficientPrivilegeError`. `verify()` raises for an EdDSA token with no bound or passed audience.
- Spec rule: I2, platform-service.md:75; I7, :80; I14, :87.
- Verdict: accept. Both earlier rejects are closed.

## 2efe8bb: sign-in, session, refresh rotation, JWKS, introspect internal

- Check: uc-021 8 checks (reused rotated refresh 401 and that session ended); `test_introspect_is_not_served_by_the_public_app`.
- Spec rule: I3, :76; I8, :81; decision rows on refresh tokens and one tenant per email.
- Verdict: accept.
- Notes: two tabs refreshing at once end the session by design (the second presentation is a reuse). Every
  authenticated request writes `last_seen_at`, one UPDATE per read.

## b104823: me, teams, members, invites

- Check: uc-023 6 checks; the store locks active admins (`_lock_admins`) before the last-admin test.
- Spec rule: I1, :74 (team from `X-Team-Id` among the token's teams; admin role re-read from the database on every
  write); I6, :79; I10, :83.
- Verdict: accept.
- Notes: removal revokes the person's sessions in every team of the tenant and disables only their keys for this
  team; that matches I10's wording, but say so in the spec so a later change does not narrow the sessions part.

## 16abf29: API keys

- Check: platform-service suite (`test_api_keys.py`); introspection compares with `hmac.compare_digest` (I11); no
  logger call anywhere in `ops_platform` or `ops_identity` (I12).
- Spec rule: I4, :77; I11, :84; I12, :85; decision row for 404 across teams (I2 row amended in f26fa0a).
- Verdict: accept.
- Notes: an unknown key id returns before the hash compare, so timing tells an id exists; ids are not secret.

## f26fa0a: audit route, I7 bulk atomicity

- Check: uc-025 5 checks; `set_role` and `remove` write rows and audit entries in one `tenant_tx`.
- Spec rule: I7, :80 (admins read their team's entries; a team with scope `all` reads the tenant).
- Verdict: accept.
- Notes: this commit deleted twelve lines of `evidence/009/review.md`, since restored; a file outside the card's
  scope changed in a feature commit, the failure the pinned-parent commit rule now guards.

## bfb6972: SECURITY DEFINER lookups, deployment-role test, OpenAPI sweep

- Check: as `ops_platform_tenant` with no tenant set, `users` shows 0 rows and `platform_users_by_email` returns the
  one matching row; `test_least_privilege` and `test_boundary` pass.
- Spec rule: I2, :75; I3, :76; decision row on pre-tenant lookups.
- Verdict: accept, with a follow-up I would block the next migration on.
- Defect (probed): the functions `SET search_path = public` and name tables unqualified, and Postgres searches
  `pg_temp` first when it is not listed. As the tenant role, `CREATE TEMP TABLE users`, insert a row, `GRANT SELECT`
  to `ops_platform_lookup`, and `platform_users_by_email` returns the forged row and hides the real one. The effect
  stays in that session and needs SQL as the app, so it widens nothing today. Fix: `SET search_path = pg_catalog,
  public, pg_temp` and `public.`-qualified tables in all four functions.

## 2551030: ops_identity

- Check: ops_identity suite green (read key on a POST is 403 `scope_required`, `test_identity.py:193`); platform's
  `test_identity_seam`.
- Spec rule: I1, :74; I9, :82 (scopes from the method, no per-route opt-in); I14, :87 (JWKS verifiers bound to the
  service's audience).
- Verdict: accept.
- Notes: the 30-second key cache is what spec line 62 allows ("near-immediate"); `last_used_at` then updates only on
  a cache miss. Invalid keys are not cached, so every bad key reaches introspection.

## ffa4c6b: per-service Ed25519 tokens on introspect

- Check: `test_service_tokens.py`, `test_introspect.py`; uc-026's service token on the public mount is 401.
- Spec rule: I13, :86 (own key; `sub` bound to the kid's service; tenant claim required except on introspect, which
  runs before a tenant is known); I8, :81.
- Verdict: accept.
- Notes: a person token is refused on internal mounts (`kind != service`) and a service token on public ones
  (`kind != person`); the dev key is accepted only when `environment` is dev.

## d9b2684: make, stack, docs

- Check: both uvicorn servers bind `127.0.0.1`; the docs name no secret store, person or local path.
- Spec rule: I8, :81 (the internal port is never exposed by the public host).
- Verdict: accept.

## d3a380d: migration 0005 pins the lookup functions' search_path

- Check: my bfb6972 probe rerun on `ops_probe_c006` upgraded to `0005_lookup_paths`. As `ops_platform_tenant`, a
  temp `users` granted to `ops_platform_lookup` no longer reaches `platform_users_by_email`: the real row comes back,
  the forged-only email returns nothing, and `proconfig` reads `search_path=pg_catalog, public, pg_temp`.
  Platform-service 68 passed in two `scripts/verify-head.sh` runs on HEAD (7d69b37, 71a9e34).
- Spec rule: I2, platform-service.md:75; the decision row on pre-tenant lookups (the tenant role may only execute
  them).
- Verdict: accept. Closes the bfb6972 follow-up.
- Notes: the new test inserts the forged row under the real person's email and asserts the real one returns, so it
  fails without 0005 (the author saw it red). Downgrade restores 0004's loose path exactly, which is right for a
  downgrade but means a rollback reopens the shadow.

## Triage

Every finding in this file, with its disposition.

| Finding | Where | Disposition |
|---|---|---|
| `verify()` checked `aud` only when passed | 81ae072 | Fixed in 25781ce; audience bound on the Ed25519 verifier and required for EdDSA |
| Single-column FKs let a tenant-A row point at tenant B's team or user | 3745fcb | Fixed in 25781ce; probed refused as the tenant role |
| Tenant role could UPDATE and DELETE audit entries | 3745fcb | Fixed in 25781ce; DELETE, UPDATE and TRUNCATE probed refused |
| Definer lookups read a caller's temp table (`search_path = public`) | bfb6972 | Fixed in d3a380d (migration 0005); probe returns the real row |
| A feature commit deleted twelve lines of `evidence/009/review.md` | f26fa0a | Fixed: restored, and the pinned-parent commit rule now stops a stale private index from undoing another lane |
| Two agents-service gateway tests failed in the review run ("approval token is not signed by the review service") | review run of d9b2684 | Fixed: shared-OPA state, not this card; 7d69b37 gives every suite and use case its own OPA |
| `committed_count` reads `HEAD:`, so "may not grow" holds only before commit | 4821822 (first reviewer) | Defer: compare against the merge-base once there is a PR flow |
| `contract.typed` and `openapi.typed` treat 204 and SSE differently | 4821822 (first reviewer) | Defer: fold into one function with the next OpenAPI change |
| Removal revokes sessions in every team but disables keys only for this team | b104823 | Defer: matches I10's wording; state it in the spec so a later change does not narrow it |
| No negative cache for invalid API keys; each one reaches introspection | 2551030 | Defer: add with rate limiting on the internal mount |
| `last_used_at` updates only on a key-cache miss | 2551030 | Unnecessary: spec line 62 allows the brief cache |
| Every authenticated request writes `last_seen_at` | 2efe8bb | Defer: a cost to measure under load, not a correctness issue |
| Two tabs refreshing at once end the session | 2efe8bb | Unnecessary: the reuse rule as designed |
| An unknown key id returns before the hash compare | 16abf29 | Unnecessary: key ids are not secret |
| 0005's downgrade restores the loose search path | d3a380d | Unnecessary: no downgrades run before launch, and chains are squashed then |

verdict: approve
