# ADR-0013 Auth provider seam

Status: option, not decided. No ADR had been confirmed as of 2026-10-10; each one records the options, a scoring and a recommendation, and the build keeps a seam open so the choice can differ per enterprise deployment.

## Context

ADR-0005 decides how workflows are identified and how they act for a person or process
(`docs/architecture/decisions/identity-and-entitlement.md:31`). It does not decide how a
person signs in to the console. The console now has human sign-in in the mock: password with TOTP,
SSO by verified domain, invites, forced MFA enrolment, session expiry, account security, and a
step-up before money approvals ([sign-in library](../../packages/ops_signin/overview.md)).

Three forces shape the choice. Banks sign staff in through their own IdP (Entra ID or Okta) and
expect its MFA and joiner-leaver process to apply. Some accounts sit outside the IdP's domains
(contractors, auditors) and need a password with a second factor. Editions outside banking
may prefer a hosted identity service such as Firebase. Demos and UI review need instant sign-in with
no external service.

## Options

| Option | What it is |
|---|---|
| A. Firebase everywhere | The console imports the Firebase SDK. Banks connect their IdP to Firebase (Identity Platform) through OIDC or SAML |
| B. IdP only | The console speaks OIDC to the bank's IdP and nothing else. No password accounts |
| C. Provider seam with adapters | One `AuthProvider` interface; adapters for mock, OIDC and Firebase; the workspace policy from the API decides what is offered |

| Criterion | Weight | A | B | C |
|---|---|---|---|---|
| Bank IdP owns sign-in and MFA for its domains | 25 | 3 | 5 | 5 |
| Identity data stays where the bank requires | 20 | 2 | 5 | 5 |
| Password and TOTP fallback for accounts outside the IdP | 15 | 4 | 1 | 4 |
| Demo and UI review without an external service | 15 | 2 | 1 | 5 |
| Step-up before money approvals | 15 | 3 | 4 | 4 |
| Cost to build and maintain | 10 | 4 | 4 | 3 |
| Weighted total (of 500) | | 290 | 355 | 450 |

## Decision

Option C. The console never imports Firebase or any identity SDK outside an adapter file.

| Part | Decision |
|---|---|
| Interface | `AuthProvider` (`apps/console/src/lib/auth/provider.ts:46-76`): `getSession`, `onSessionChange`, `signInWithPassword`, `signInWithGoogle`, `startSso`, `completeSso`, `completeInvite`, `sendReset`, `resetPassword`, `mfa.setup`, `mfa.enrol`, `mfa.verify`, `reauthenticate`, `signOut`. Errors are `AuthError` with a code (`provider.ts:78-86`) |
| Adapters | `mock`, `oidc`, `firebase` (`provider.ts:47`). Firebase is optional and its SDK is imported only inside its adapter (`apps/console/src/lib/auth/providers/firebase.ts:4`) |
| Selection | One env value, `NEXT_PUBLIC_AUTH_PROVIDER`, read only in `apps/console/src/lib/api/index.ts:14-20`; `mock` when unset. An adapter that is chosen but not wired fails every call with the env values to set (`apps/console/src/lib/auth/providers/unconfigured.ts:3-9`) |
| Policy | What a workspace allows comes from the API: methods, SSO provider and verified domains, MFA required, session length, allowed invite domains, self-signup (`apps/console/src/lib/types/sign-in.ts:21-32`). The login screen reads it (`apps/console/src/hooks/auth-queries.ts:32`). Adapters carry no policy |
| Bank default | `oidc` against the bank's IdP, SSO on for its verified domains, password with TOTP as the fallback, MFA required, self-signup off. People join by invite |
| Step-up | Approving a money movement needs a step-up token from a re-authentication by the same person in the last 5 minutes. The API enforces it and refuses with 422 otherwise (`apps/console/src/lib/api/mock/index.ts:148-152`); the console asks only when refused (`apps/console/src/components/auth/reauth-dialog.tsx:113-141`) |
| Where the seam sits in Next.js | Client side. Hooks import `authProvider` from `@/lib/auth` (`apps/console/src/lib/auth/index.ts:2`); the app shell guards every non-auth route with `useSession` and the policy (`apps/console/src/app/_shell/app-shell.tsx:27-58`). The guard is for the person's convenience; the API checks the session on every call |

| Capability | mock | oidc | firebase |
|---|---|---|---|
| Password sign-in | Yes, seeded users | Through the IdP's own login page only | Yes |
| SSO by domain | Simulated IdP round trip | Yes, authorisation code with PKCE | Through Identity Platform OIDC or SAML |
| Google sign-in | Refused as not configured | If the IdP federates Google | Yes |
| TOTP enrolment and challenge | Yes, code `123456` | IdP's MFA; console TOTP for fallback accounts | Yes (Firebase TOTP MFA) |
| Invite completion | Yes | Yes, through the IdP | Yes |
| Password reset | Yes, preview link | IdP's own reset | Yes |
| Step-up | Password or TOTP, 5-minute token | IdP re-authentication (`max_age=0`) | Recent sign-in or TOTP |
| State in the code today | Complete (`apps/console/src/lib/api/mock/auth/index.ts:63-251`) | Stub (`providers/oidc.ts:5`) | Stub (`providers/firebase.ts:5`) |

### How a human session becomes the `sub` of a delegation token

The person's identity in `Session.user.id` is the subject the IdP asserted. When that person starts a
run, chats with an agent, or approves a drafted action, the API exchanges the person's access token
for a delegation token as ADR-0005 describes: `sub` is the person, `act` is the workflow identity,
short expiry, audience the data gateway (`identity-and-entitlement.md:31`). With the `oidc`
adapter the token presented is the bank IdP's, so `sub` is the bank's own subject. With `firebase`,
the API verifies the Firebase token and maps it to the workspace member, and the gateway mints the
delegation token itself, which is the fallback ADR-0005 already allows when the IdP cannot issue `act`
claims (`identity-and-entitlement.md:54-55`). For a money approval, the case service signs
the human-approval token (`identity-and-entitlement.md:35`) only after the step-up has
passed, and records the step-up time on the approval. This ADR adds no new token type.

## Consequences

The console gains a fixed contract that every adapter must satisfy, and the demo runs with no
external service. Policy lives in one place, so a bank admin changes what the login screen offers
without a release.

Strongest counter-argument: an interface written before a real adapter exists will be shaped by the
mock, and the first OIDC adapter will find methods that do not map (an IdP owns its own password
reset and MFA enrolment, so `resetPassword` and `mfa.*` have no OIDC meaning). Answer: those methods
already have a defined failure (`not_configured`), and the policy hides the controls that would call
them when SSO covers the domain. If the OIDC adapter needs a method the interface lacks, the interface
changes once, in one file, with the mock updated alongside.

A second cost: the seam is client side, so tokens sit in the browser. A bank may require a server-side
session (httpOnly cookie, code exchange in a route handler). That moves the token handling into
Next.js route handlers behind the same interface; the components do not change.

What would change this decision:

- The bank requires all identity traffic to pass through a server it controls. Then the `oidc` adapter
  becomes a thin client over a backend-for-frontend, and the seam stays.
- No tenant ever needs a password fallback or a non-bank IdP. Then Option B is simpler and the mock
  remains only for demos.
- Firebase becomes the platform standard for every edition, including banks. Then Option A
  costs less to run, subject to the bank's data residency review.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Interface, env selection, mock adapter for every flow; policy from the API; step-up enforced by the API on single, bulk and chat approvals; OIDC and Firebase adapters as stubs that name their env values | OIDC adapter wired against the bank's IdP, with IdP step-up through `max_age` and `acr_values`; server-side session in Next.js route handlers if the bank requires it; Firebase adapter for non-bank tenants; SCIM; passkeys |

## Sources

- `apps/console/src/lib/auth/provider.ts`, `index.ts`, `providers/oidc.ts`, `providers/firebase.ts`, `providers/unconfigured.ts`
- `apps/console/src/lib/api/index.ts`; `apps/console/src/lib/api/mock/auth/index.ts`; `apps/console/src/lib/api/mock/index.ts`
- `apps/console/src/lib/types/sign-in.ts`; `apps/console/src/hooks/auth-queries.ts`
- `apps/console/src/app/_shell/app-shell.tsx`; `apps/console/src/components/auth/reauth-dialog.tsx`
- `docs/architecture/decisions/identity-and-entitlement.md`; `docs/architecture/decisions/assurance.md` (structure)
- [sign-in library](../../packages/ops_signin/overview.md)
