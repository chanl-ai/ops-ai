# Identity and sign-in

Status: current. Checked against the release's sign-in code.

Staff should sign in to Ops AI the way they sign in to everything else at the bank: through the company's identity
provider, with its multi-factor rules, and lose access the day the provider says so. This page covers single sign-on
over OIDC and SAML, passwords for installs without a provider, sessions, and the fresh sign-in a sensitive approval
asks for.

## Try it

A Security admin connects the company's provider in the console.

<!-- site: steps -->
1. Open Settings › Security › Sign-in and add a provider: OIDC (for example Microsoft Entra ID or Okta) or SAML 2.0.
2. For SAML, paste the provider's metadata address or file; Ops AI reads its sign-in address and signing
   certificates. Give the provider the Ops AI entity ID and reply address the dialog shows.
3. Add the company's email domain and publish the DNS TXT record the console gives you, then press Verify.
4. Sign out and sign in with a company email. The console sends you to the provider and back.

## How it works

- The email's domain picks the organisation and its provider. A domain routes nobody until its TXT record is
  verified.
- OIDC uses the authorization code flow with PKCE (S256), pins the issuer and accepts only asymmetric signing
  algorithms. SAML needs a signed response; signed requests and encrypted assertions are supported. Sign-in started
  from the provider's app portal (an Ops AI tile) is accepted for a provider that allows it.
- A person's first sign-in through the provider creates their account. Group rules can add them to teams with a role;
  a first sign-in never makes anyone an admin.
- Every failure shows the person one message, "sign-in refused"; the reason goes to the log.
- A session lasts up to 8 hours. The access token inside it lives 15 minutes and is renewed with a refresh token that
  works once; a reused refresh token is refused and recorded in the audit log.
- Multi-factor authentication is your provider's: Ops AI asks it to sign the person in, and it applies its own rules.

## Options

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Sign-in providers and domains | Which provider serves which verified email domain | None: passwords only | A Security admin, in Settings › Security › Sign-in |
| Group rules | A provider group adds its members to a team with a role (never admin). With "remove when missing" on, a membership a group gave ends when the person leaves the group | No rules | A Security admin, on the provider |
| Company sign-in required | People on a verified domain sign in only through the provider. Up to three named Security admins keep a password as a break-glass way in; each use is audited and the Security admins are told | Off | A Security admin, in Governance › Policies |
| Step-up on every approval | Every approver signs in again before deciding. Off: only the operations that ask for it, such as payments, need a sign-in less than five minutes old | Off | A Security admin, in Governance › Policies |
| Passwords | For an install with no provider: at least 12 characters, stored as a salted PBKDF2-SHA256 hash with 600,000 iterations; locked for a while after 5 failures in 15 minutes; reset by email | On while no provider is required | Each person, in My security |
| Invites | An admin invites by email with a single-use link | | A team admin, in Settings › Members |

## Limits

- SCIM provisioning is planned. Until then accounts are created at first sign-in and group rules are applied at each
  sign-in, so a person removed at the provider keeps their Ops AI session until it ends (at most 8 hours).
- A test sign-in that changes nothing is planned; test a new provider with a test account.
- Group rules are set through the API today; editing them in the console is planned.

## Next

<!-- site: cards -->
- **[Access, approvals and audit](access-approvals-and-audit.md)**: What each role may do once signed in.
- **[Tenancy and isolation](tenancy-and-isolation.md)**: How teams and organisations are kept apart.
- **[API keys and the HTTP API](../reference/http-api.md)**: How scripts and services sign in.
