# 13 Sign-in and sessions

Status: draft for review.

Builds on ADR-0013 (auth provider seam) and ADR-0005 (workflow identity and delegation) in
`../architecture/decisions/`, and on `governance-and-admin.md` (members, roles, audit log). The
console mock is the reference for UI and API shape: `apps/console/src/lib/auth/**`,
`apps/console/src/lib/types/{sign-in,account,invites}.ts`, the matching
`apps/console/src/lib/api/{sign-in,account,invites}-contract.ts`, the mocks under
`apps/console/src/lib/api/mock/{auth,sign-in-policy,sessions,invites}/`, and the routes `/login`,
`/sso`, `/forgot-password`, `/reset-password/[token]`, `/mfa/*`, `/invite/[token]`, `/signup`,
`/settings/sign-in`, `/account` and `/account/security`.

## 1. Scope

This spec covers people: how a member of bank staff signs in to the console, proves a second factor,
keeps or loses a session, joins by invitation, manages their own account, and re-authenticates before
approving a money movement. It also covers the workspace sign-in policy that decides which of these
the login screen offers.

Workflow identity, process principals for mailboxes, delegation tokens (`sub` and `act`) and the
human-approval token bound to an action's input are ADR-0005's
(`docs/architecture/decisions/identity-and-entitlement.md:31`, `:35`). This spec ends where
a signed-in person's identity is handed to that design; ADR-0013 says how the hand-off works.

| In | Phase |
|---|---|
| Password sign-in with TOTP second factor | 1 |
| SSO by verified email domain (Entra ID, Okta, generic OIDC, SAML metadata) | 1 |
| Forced MFA enrolment when the policy requires it | 1 |
| Forgot and reset password | 1 |
| Invitation links; self-signup off by default | 1 |
| Session expiry and the sign-in-again screen | 1 |
| Account: profile, password change, MFA devices, recovery codes, sessions | 1 |
| Settings → Sign-in: methods, SSO connection and domains, security, self-signup | 1 |
| Step-up re-authentication before a money-movement approval, enforced by the API | 1 |
| SCIM provisioning, passkeys, device trust, IP-bound sessions | Later (section 9) |

## 2. Entities

Fields are as built in the mock. Where the mock has no stored entity yet, the row says what holds the
data today.

| Entity | Fields | Notes |
|---|---|---|
| `Session` | `user` (`id`, `name`, `email`, `teamIds[]`, `role` `admin`/`member`/`viewer`), `mfaEnrolled`, `authMethod` (`password`, `sso`, `google`), `issuedAt`, `expiresAt` | `apps/console/src/lib/auth/provider.ts:10-24`. An expired session is still returned so the console can name who was signed in (`provider.ts:48`) |
| `SignInResult` | `signed_in` with `session`, or `mfa_required` with `challengeId` and `email` | `provider.ts:27` |
| `SignInPolicy` | `methods` (`password`, `sso`, `google`), `sso` (`provider` `entra`/`okta`/`oidc`/`saml`, `metadataUrl`, `metadataFileId?`, `metadataFileName?`, `domains[]`, `lastTest?`), `mfaRequired`, `sessionHours`, `allowedDomains[]`, `selfSignup`, `updatedAt`, `updatedBy` | `apps/console/src/lib/types/sign-in.ts:21-32`. One per workspace |
| `SsoConnection` | The `sso` object on the policy: provider, metadata URL or uploaded metadata file, last test result (`ok`, `at`, `message`) | `sign-in.ts:15-23`. One connection per workspace in phase 1 |
| `VerifiedDomain` | `domain`, `verified`, `txtRecord`, `verifiedAt?` | `sign-in.ts:7-13` (`SsoDomain`). A domain is verified by publishing the DNS TXT record |
| `MfaDevice` | `id`, `kind` (`totp`, `recovery_codes`), `label`, `addedAt`, `lastUsedAt?`, `remaining?` | `apps/console/src/lib/types/account.ts:17-25` |
| `RecoveryCode` | Strings returned once by enrolment (`MfaSetup.recoveryCodes`) or by regenerate; stored as a count (`remaining`) on the `recovery_codes` device | `provider.ts:29-36`, `account.ts:23-24` |
| `MfaSetup` | `secret` (base32), `otpauthUrl`, `recoveryCodes[]` | `provider.ts:29-36` |
| `Invite` | `token`, `email`, `team`, `role`, `invitedBy`, `invitedAt`, `expiresAt`, `state` (`pending`, `expired`, `accepted`), `sso`, `ssoProviderLabel?`, `mfaRequired` | `apps/console/src/lib/types/invites.ts:5-19` (`InvitePreview`). Links last 7 days (`apps/console/src/lib/api/mock/invites/index.ts:10`) |
| `StepUpToken` | `token`, `expiresAt` | `provider.ts:39-42` (`StepUp`). Valid 5 minutes and reusable inside that window (`apps/console/src/lib/api/mock/auth/index.ts:33`, `:240`) |
| `UserSession` (device) | `id`, `device`, `browser`, `location`, `ip`, `lastSeenAt`, `createdAt`, `current` | `account.ts:27-36` (`AccountSession`) |
| `AccountProfile` | `id`, `name`, `email`, `initials`, `team`, `role`, `authMethod` (`password`, `sso`), `ssoProvider?` | `account.ts:5-15` |

`Review.movesMoney` is set by the API when approving runs a money-movement operation
(`apps/console/src/lib/types/domain.ts:172`). `ReviewDecisionInput.stepUpToken` carries the step-up
(`domain.ts:208`), and so do `reviews.bulkDecide(…, { stepUpToken })`
(`apps/console/src/lib/api/contract.ts:127`) and the chat approval widget action
(`apps/console/src/lib/types/chat.ts:105-106`).

## 3. Flows

### 3.1 Password sign-in with MFA

1. `/login` loads the policy (`useSignInPolicy`, `apps/console/src/hooks/auth-queries.ts:32`) and shows the methods it allows.
2. The person enters email and password. If the email's domain is a verified SSO domain, the form switches to SSO (3.2).
3. `authProvider.signInWithPassword` checks the password. A wrong pair returns `invalid_credentials` with one message for both cases (`mock/auth/index.ts:144`).
4. If the person has MFA enrolled, the result is `mfa_required` with a challenge id (`mock/auth/index.ts:145-148`); the page sends them to `/mfa/verify?challenge=…&next=…` (`apps/console/src/app/(auth)/login/page.tsx:24`).
5. They enter the 6-digit code; `mfa.verify` checks it against the challenge and returns the session (`mock/auth/index.ts:224-231`).
6. The browser goes to `next`, which `safeNext` limits to a console path (`apps/console/src/lib/auth/next-path.ts:6-9`). Sign-in clears cached queries because every query now runs as a different person (`auth-queries.ts:40-44`).

### 3.2 SSO by domain

1. On `/login`, an email on a verified SSO domain puts the form in SSO mode and shows a notice (`apps/console/src/components/auth/login-form.tsx:44-45`). `/sso` takes an email or domain directly.
2. `authProvider.startSso({ email })` returns the IdP redirect URL; the page appends `next` and navigates (`login/page.tsx:50-54`).
3. The IdP returns to `/sso/callback?code=…`; `completeSso(code)` finishes and returns a session with `authMethod: 'sso'`.
4. The IdP enforces its own MFA, so an SSO session does not stop at the console's challenge (`mock/auth/index.ts:171`).

### 3.3 Forced MFA enrolment

1. The app shell computes `needsMfa`: signed in, policy `mfaRequired`, session not enrolled (`apps/console/src/app/_shell/app-shell.tsx:51`).
2. It redirects to `/mfa/setup?next=…` before any page renders (`app-shell.tsx:54`, `:58`).
3. `mfa.setup` returns a secret, an `otpauth://` URL and recovery codes. The page shows the setup key and link in place of a QR code, and the recovery codes once (`apps/console/src/components/auth/mfa-setup-form.tsx:16-17`).
4. The person enters the first code; `mfa.enrol` confirms it and returns the session with `mfaEnrolled: true` (`mock/auth/index.ts:215-223`).

### 3.4 Forgot and reset

1. `/forgot-password` takes an email and calls `sendReset`. The confirmation reads the same whether or not the account exists (`mock/auth/index.ts:192`, `apps/console/src/components/auth/forgot-password-form.tsx:24`).
2. The mock has no mailbox, so it returns `previewUrl` and the page links to it; other adapters never set it (`provider.ts:63`).
3. `/reset-password/[token]` takes a new password of at least 12 characters. The token is single use (`mock/auth/index.ts:199-207`).
4. The page says the link works once for an hour. The mock does not expire reset tokens; see Q8.

### 3.5 Invite accept

1. A workspace admin invites from Settings → Members; each invite gets a link token (`apps/console/src/lib/api/mock/settings/index.ts:89-99`).
2. `/invite/[token]` loads `invites.get`. Unknown token shows "not valid"; expired and accepted invites show their own states (`apps/console/src/app/(auth)/invite/[token]/page.tsx:54-64`).
3. The person gives their name, and a password unless the email is on a verified SSO domain. `invites.accept` creates the account (`mock/invites/index.ts:79-96`).
4. A password account is then signed in with the password just set; an SSO account is sent to the IdP (`invite/[token]/page.tsx:31-37`).
5. When the policy requires MFA, `next` is `/mfa/setup` (`mock/invites/index.ts:96`); the shell would also force it (3.3).

### 3.6 Sign out and expiry

1. `signOut` ends the session and emits a change; cached queries are cleared (`mock/auth/index.ts:245-248`, `auth-queries.ts:59`).
2. A signed-out visit to any console route redirects to `/login?next=<path>` (`app-shell.tsx:53`).
3. When `expiresAt` has passed, `useSession` reports `expired` and the shell replaces the console with "Your session has ended", naming the person and returning to the same path after sign-in (`auth-queries.ts:20`, `app-shell.tsx:57`, `:79-94`).
4. From `/account/security` a person can sign out one other device or every device except this one (`apps/console/src/lib/api/mock/sessions/index.ts:109-124`).

### 3.7 Step-up before a money approval

The rule: the API refuses to approve a review whose action moves money unless the request carries a
step-up token from a re-authentication by the same person in the last 5 minutes. The refusal is 422
with a message naming step-up. The console asks for the step-up when refused; it never decides on its
own that a step-up is unnecessary.

1. The client sends the action with the cached step-up token if one is still valid (`apps/console/src/components/auth/reauth-dialog.tsx:103-123`).
2. The API checks `movesMoney` on the review. If set, it verifies the token: unknown, expired, or issued to another account each return 422 (`apps/console/src/lib/api/mock/index.ts:148-152`, `:974`).
3. On a step-up refusal, `useStepUpGate` opens "Confirm it is you". Password accounts enter their password; SSO accounts with an authenticator enter a code; SSO accounts without one are told to sign in again (`reauth-dialog.tsx:33-34`, `:95-96`).
4. `reauthenticate` returns a token valid for 5 minutes, cached for the tab, and the action is retried once with it (`reauth-dialog.tsx:113-141`, `mock/auth/index.ts:233-244`).
5. Closing the dialog raises `StepUpCancelled`, which callers treat as a cancel.
6. The audit log records the approval with "step-up verified" (`mock/index.ts:975`).

| Channel | How the token travels | State in the mock |
|---|---|---|
| Reviews page, one review | `reviews.decide(id, { …, stepUpToken })` through `withStepUp` | Wired (`apps/console/src/app/reviews/page.tsx:131`) |
| Reviews page, bulk | `reviews.bulkDecide(ids, 'approved', reason, { stepUpToken })`. One token covers the batch; if any open review in the batch moves money and the token is missing or stale, nothing in the batch is decided | Wired (`reviews/page.tsx:303`, `mock/index.ts:993-1007`) |
| Chat approval widget | `WidgetAction { type: 'approve', stepUpToken }` | The mock passes it to `decide` (`apps/console/src/lib/api/mock/chat/index.ts:488`). The widget sends `{ type: 'approve' }` without a token and has no step-up gate, so a money approval from chat is refused with 422 until the widget uses `useStepUpGate` |
| Microsoft Teams and email approvals (`09`) | Must carry a step-up from the same person; the channel opens the console's step-up page | Not built |

## 4. Policy and what the login screen shows

The policy comes from the API (`apps/console/src/lib/api/sign-in-contract.ts:3-18`). Adapters never
decide what is offered. The seeded Northfield policy: password and SSO on, Google off, Entra ID for
`northfield.ca`, MFA required, 10-hour sessions, invites from `northfieldbank.com` and
`northfield.ca`, self-signup off (`apps/console/src/lib/api/mock/sign-in-policy/index.ts:13-27`).

| Policy field | Effect |
|---|---|
| `methods.password` | Shows the password field. Off with SSO on, every email goes to SSO (`login-form.tsx:45`) |
| `methods.sso` | Shows "Continue with SSO" and lets a verified domain switch the form to SSO. Cannot be turned on without a verified domain (400) |
| `methods.google` | Shows "Continue with Google". At least one method must stay on (400) |
| `sso.provider`, `sso.metadataUrl` or metadata file | Which IdP `startSso` targets. The URL must be https; one of URL or file is required |
| `sso.domains[].verified` | An email on a verified domain is sent to SSO whatever else is on. An invite to such an email creates an SSO account with no password |
| `mfaRequired` | Unenrolled sessions are sent to `/mfa/setup` before any page. The last authenticator cannot be removed (409). Invite acceptance continues to MFA setup |
| `sessionHours` | Hours a session stays signed in without activity, 1 to 168 (400 outside). Applies at the next sign-in |
| `allowedDomains[]` | Email domains people can be invited from; empty means any |
| `selfSignup` | On: the login screen links to `/signup`, which continues with SSO. Off: the login screen says to ask an admin, and `/signup` says the same (`login-form.tsx:109-118`, `apps/console/src/app/(auth)/signup/page.tsx:11-25`) |

If the policy cannot be loaded, the login screen offers password sign-in and says the other options
could not be loaded (`login/page.tsx:43`, `:48`).

Bank default: `oidc` adapter against the bank's IdP, SSO on for the bank's verified domains, password
with TOTP kept on as a fallback for accounts outside those domains, MFA required, self-signup off.

## 5. Operations

Mock API operations, from the contracts and mocks. Errors are HTTP status plus the condition.

### 5.1 AuthProvider (`apps/console/src/lib/auth/provider.ts:46-76`)

| Operation | Request | Response | Errors (`AuthError.code`) |
|---|---|---|---|
| `getSession` | | `Session` or null | `not_configured` (unwired adapter) |
| `onSessionChange` | listener | unsubscribe | |
| `signInWithPassword` | `email`, `password` | `SignInResult` | `invalid_credentials` |
| `signInWithGoogle` | | `SignInResult` | `not_configured` in the mock |
| `startSso` | `{ email? , domain? }` | `{ redirectUrl }` | |
| `completeSso` | `code` | `SignInResult` | `invalid_token` |
| `completeInvite` | one-time `signInCode` | `SignInResult` | `invalid_token` |
| `sendReset` | `email` | `{ previewUrl? }` | none, by design |
| `resetPassword` | `token`, `password` | | `invalid_token`; `invalid_credentials` under 12 characters |
| `mfa.setup` | | `MfaSetup` | `no_session` |
| `mfa.enrol` | `code` | `Session` | `no_session`, `invalid_code` |
| `mfa.verify` | `code`, `challengeId?` | `Session` | `no_challenge`, `invalid_code` |
| `reauthenticate` | `{ method: 'password', password }` or `{ method: 'totp', code }` | `StepUp` | `no_session`, `invalid_credentials`, `invalid_code` |
| `signOut` | | | |

### 5.2 Sign-in policy (`api.signInPolicy`)

| Operation | Request | Response | Errors |
|---|---|---|---|
| `get` | | `SignInPolicy` | |
| `save` | `SignInPolicyPatch`: one of `methods`, `sso`, `security`, `signup` (`sign-in.ts:37-41`) | `SignInPolicy` | 400 no method left on; 400 SSO on without a verified domain; 400 no metadata URL or file; 400 metadata URL not https; 400 session outside 1 h to 7 days; 400 an allowed domain is not a domain (`mock/sign-in-policy/index.ts:51-63`) |
| `addDomain` | `domain` | `SignInPolicy` | 400 not a domain; 409 already listed |
| `verifyDomain` | `domain` | `SignInPolicy` | 404 not listed; 422 TXT record not found |
| `removeDomain` | `domain` | `SignInPolicy` | 404 not listed; 409 the only verified domain while SSO is on |
| `testConnection` | | `SsoTestResult` | Failure is a result with `ok: false` |

### 5.3 Invites (`api.invites`, public routes)

| Operation | Request | Response | Errors |
|---|---|---|---|
| `get` | `token` (`GET /invites/:token`) | `InvitePreview` | 404 unknown token. Expired and accepted invites return with their state |
| `accept` | `token`, `{ name, password? }` (`POST /invites/:token/accept`) | `InviteAcceptResult` (`email`, `name`, `team`, `authMethod`, `next`) | 410 expired; 409 already accepted; 400 name missing; 400 password under 12 characters or containing the email's local part (`mock/invites/index.ts:83-91`) |
| `settings.members.invite` | `emails[]`, `role`, `teamId?` | `BulkResult` per email | Per row: not an email, outside the allowed domain, already in the team |

### 5.4 Account (`api.account`, the signed-in person from the session)

| Operation | Request | Response | Errors |
|---|---|---|---|
| `profile` | | `AccountProfile` | |
| `updateProfile` | `{ name }` | `AccountProfile` | 400 name outside 2 to 80 characters |
| `changePassword` | `{ password }`, after `reauthenticate` with the current password | | 403 SSO account; 400 under 12 characters |
| `mfa.list` | | `MfaDevice[]` | |
| `mfa.regenerateCodes` | | `{ codes, devices }` | |
| `mfa.remove` | device `id` | `MfaDevice[]` | 404; 409 last authenticator while MFA is required |
| `sessions.list` | `ListParams<SessionFilters>` | `ListResult<AccountSession>` | |
| `sessions.revoke` | session `id` | | 404; 400 the current session |
| `sessions.revokeOthers` | | `{ revoked }` | |

### 5.5 Step-up on reviews

| Operation | Request | Response | Errors |
|---|---|---|---|
| `reviews.decide` | `id`, `ReviewDecisionInput` with `stepUpToken` when approving a money movement | `Review` | 422 step-up missing, expired, or another account's; plus the existing 400 and 409 rules |
| `reviews.bulkDecide` | `ids`, `decision`, `reason?`, `{ stepUpToken? }` | `BulkResult` | 422 for the whole batch when it includes an open money review and the step-up fails |
| `chat.widgetAction` | `{ type: 'approve', stepUpToken? }` | widget | 422 as `decide` |

## 6. Pages and components

| Route | Component | What it does | Designed states |
|---|---|---|---|
| `/login` | `LoginForm` | Policy-driven methods; switches to SSO for a verified domain; links to reset and, when allowed, signup | Loading skeleton; policy load error with password fallback; wrong credentials; SSO notice; pending per method |
| `/sso` | `SsoForm` | Email or domain to the IdP | Pending; error |
| `/sso/callback` | page | Finishes SSO from `code` | Signing in; "Sign-in did not finish" with retry |
| `/forgot-password` | `ForgotPasswordForm` | Sends the reset email | Sent, same copy either way; mock preview link |
| `/reset-password/[token]` | `ResetPasswordForm` | Sets a new password | Invalid or used token; too short; done |
| `/mfa/setup` | `MfaSetupForm` | Setup key, otpauth link, recovery codes, first code | Loading; wrong code; needs a session |
| `/mfa/verify` | `MfaVerifyForm` | 6-digit code for a challenge | Wrong code; challenge timed out |
| `/invite/[token]` | `InviteForm` | Name and password (or SSO) to join a team | Loading; not valid (404); expired; already used; load error with retry; SSO variant; MFA-next notice |
| `/signup` | page | Self-signup through SSO, or "ask your admin" | Open; closed |
| Any console route | `AppShell` guard | Redirects signed-out and unenrolled sessions; replaces the console when expired | Loading; signed out; needs MFA; session ended |
| `/settings/sign-in` | `SignInMethodsSection`, `SignInSsoSection`, `SignInSecuritySection`, `SignInSignupSection` | Each section saves on its own and is audited (`apps/console/src/components/settings/sign-in-sections.tsx:49`, `:111`, `:218`, `:255`) | No SSO domains yet; unverified domain with TXT record; verify failure; test passed or failed; save errors per rule in 5.2 |
| `/account` | profile page with `AccountTabs` | Display name; workspace team and role, read only | Loading; error; save |
| `/account/security` | `MfaDevicesTable`, `SessionsTable` | Change password (after re-auth), MFA devices, regenerate recovery codes, sign out a device or everywhere else (`apps/console/src/app/account/security/page.tsx:49`, `:79-112`) | SSO account (password managed by the IdP); no devices; codes shown once; confirm sign out everywhere |
| Dialog on Reviews and chat | `ReauthDialog`, `useStepUpGate` | "Confirm it is you" before a money approval | Password; authenticator code; SSO without authenticator (sign in again); wrong secret; cancel |

## 7. Audit events

Entries use the shape in `09` 4.3 (`docs/specs/governance-and-admin.md:87`).

| Event | Target | Written by the mock |
|---|---|---|
| Sign-in methods changed, with before and after per method | `sign_in_policy` | Yes (`mock/sign-in-policy/index.ts:54`) |
| SSO connection changed | `sign_in_policy` | Yes |
| MFA required, session length or allowed domains changed | `sign_in_policy` | Yes |
| Self-signup turned on or off | `sign_in_policy` | Yes |
| SSO domain added, verified, removed | `sign_in_policy` | Yes |
| SSO connection tested, passed or failed | `sign_in_policy` | Yes (`:109`) |
| Member invited, with role | `member` | Yes (`mock/settings/index.ts:100`) |
| Invitation accepted, and whether by SSO | `member` | Yes (`mock/invites/index.ts:95`) |
| Display name changed | `member` | Yes (`mock/sessions/index.ts:74`) |
| Password changed | `session` | Yes (`:83`) |
| Recovery codes regenerated; MFA device removed | `session` | Yes (`:94`, `:103`) |
| Device signed out; signed out everywhere else | `session` | Yes (`:115`, `:122`) |
| Money review approved with step-up verified, single and bulk | `review` | Yes (`mock/index.ts:975`, `:1007`) |
| Sign-in succeeded, failed, MFA challenge failed | `session` | No. Required in phase 1 |
| MFA enrolled | `session` | No. Required in phase 1 |
| Password reset requested and completed | `session` | No. Required in phase 1 |
| Signed out; session expired | `session` | No. Required in phase 1 |
| Step-up succeeded or failed | `session` | No. Required in phase 1 |

## 8. Provider seam

The console never imports an identity SDK. It talks to one `AuthProvider` interface
(`provider.ts:46-76`) through `@/lib/auth` (`apps/console/src/lib/auth/index.ts:2`). One env value,
`NEXT_PUBLIC_AUTH_PROVIDER`, chooses the adapter: `mock` (the default), `oidc` or `firebase`, read
only in `apps/console/src/lib/api/index.ts:14-20`. Firebase is optional. The OIDC and Firebase
adapters are stubs that fail with the env values to set (`apps/console/src/lib/auth/providers/unconfigured.ts:3-9`).
What a workspace allows is policy from the API. ADR-0013 records the decision, the options it beat,
and how a human session becomes the `sub` of an ADR-0005 delegation token.

## 9. Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Mock adapter complete for every flow in section 3 | OIDC adapter wired (authorisation code with PKCE) against the bank's IdP; Firebase adapter if a non-bank tenant wants it |
| TOTP with recovery codes; setup key and otpauth link | QR image on `/mfa/setup`, pending a QR rendering dependency (`mfa-setup-form.tsx:16-17`) |
| Recovery codes at enrolment and from Account | Recovery codes accepted on `/mfa/verify` (the form takes a 6-digit code only) |
| Invites with 7-day links; self-signup off | SCIM provisioning from the bank's IdP, so joiners and leavers flow without invites |
| Step-up by password or TOTP, 5-minute token, enforced by the API | Passkeys (WebAuthn) for sign-in and step-up; IdP-driven step-up via `max_age` and `acr_values` for SSO accounts |
| Session list with device, browser, location and IP; revoke | Device trust (managed-device signal from the IdP); binding a session to an IP range |
| Audit of policy, invite, account and step-up events | Audit of every sign-in event in section 7 that the mock does not yet write |

## 10. Open questions for the owner

| # | Question | Recommended default |
|---|---|---|
| Q1 | For a password account, is step-up the password alone, or password plus a TOTP code? The dialog asks for the password only (`reauth-dialog.tsx:33`), which repeats the first factor | Password plus TOTP when the account has an authenticator, which the policy requires for banks |
| Q2 | For an SSO account, should step-up go back to the IdP (OIDC `max_age=0`, check `auth_time`) or use a console authenticator? SSO users have no console authenticator, yet the mock marks them enrolled (`mock/auth/index.ts:171-172`) | Re-authenticate at the IdP for SSO accounts; console TOTP only for password accounts |
| Q3 | Should a step-up token bind to what it approves (review ids and amounts), as the human-approval token binds to the action input in ADR-0005? Today one token covers any money approval for 5 minutes | Keep the 5-minute window for the person, and have the API record the step-up's time on each approval; bind to the id set for bulk |
| Q4 | Is `sessionHours` an idle limit or an absolute one? The type says "without activity" (`sign-in.ts:25`) and the mock issues a fixed 10-hour session from `SESSION_HOURS` (`apps/console/src/lib/api/mock/auth/seed.ts:21`) | Idle limit from the policy plus an absolute cap of 24 hours |
| Q5 | Who may change the sign-in policy, and does turning MFA off or self-signup on need a second approver? | Platform admins only; four-eyes through Reviews for MFA off, self-signup on and removing the last verified domain |
| Q6 | The session carries `role` `admin`/`member`/`viewer` (`provider.ts:8`); `09` uses per-team `admin`/`builder`/`approver`/`viewer` (`docs/specs/governance-and-admin.md:76-80`). Which is authoritative? | Drop the workspace role from the session and read per-team roles from `09`; the session keeps `teamIds` only |
| Q7 | Should password reset be offered to an email on a verified SSO domain? | No. Show "your password is managed by <IdP>" and send no email |
| Q8 | Reset link lifetime. The page says one hour; the mock does not expire tokens | One hour, single use, invalidated by any newer reset |

## 11. Sources

Opened for this spec, with the lines cited above.

- `apps/console/src/lib/auth/provider.ts`, `index.ts`, `next-path.ts`
- `apps/console/src/lib/auth/providers/oidc.ts`, `firebase.ts`, `unconfigured.ts`
- `apps/console/src/lib/api/index.ts`
- `apps/console/src/lib/api/mock/auth/index.ts`, `seed.ts`
- `apps/console/src/lib/api/mock/sign-in-policy/index.ts`, `sessions/index.ts`, `invites/index.ts`, `settings/index.ts` (invite), `chat/index.ts` (widget action), `index.ts` (step-up guard, decide, bulk decide)
- `apps/console/src/lib/api/sign-in-contract.ts`, `account-contract.ts`, `invites-contract.ts`, `invites-http.ts`, `contract.ts`
- `apps/console/src/lib/types/sign-in.ts`, `account.ts`, `invites.ts`, `domain.ts`, `chat.ts`, `governance.ts`
- `apps/console/src/hooks/auth-queries.ts`, `account-queries.ts`
- `apps/console/src/app/(auth)/login/page.tsx`, `signup/page.tsx`, `invite/[token]/page.tsx`; `apps/console/src/app/_shell/app-shell.tsx`
- `apps/console/src/components/auth/login-form.tsx`, `reauth-dialog.tsx`, `mfa-setup-form.tsx`, `forgot-password-form.tsx`
- `apps/console/src/components/settings/sign-in-sections.tsx`; `apps/console/src/app/settings/sign-in/page.tsx`
- `apps/console/src/app/account/page.tsx`, `account/security/page.tsx`; `apps/console/src/components/account/account-tables.tsx`
- `apps/console/src/app/reviews/page.tsx`
- `docs/specs/governance-and-admin.md`
- `docs/architecture/decisions/identity-and-entitlement.md`
- `docs/console/page-plan.md` (no rows for the sign-in routes yet); `apps/console/CLAUDE.md` (layer table; no auth rows)
