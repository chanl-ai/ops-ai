# Identity and sign-in

Status: current.

Your staff already sign in to everything else through the company's identity provider, with its multi-factor rules and its leaver process. A second set of passwords for Ops AI would sit outside all of that. Ops AI signs people in through your provider over OpenID Connect (OIDC) or SAML 2.0, so the provider decides who is who and how strongly they prove it. Passwords remain available for installs that have no provider, and as a break-glass way in.

## Connect your identity provider

A Security admin connects the provider once, and everyone on the verified email domain signs in through it from then on.

<!-- site: steps -->
1. Open **Settings › Security › Sign-in** and add a provider: OIDC, for example Microsoft Entra ID or Okta, or SAML 2.0.
2. For SAML, paste the provider's metadata address or file. Ops AI reads its sign-in address and signing certificates. Give the provider the Ops AI entity ID and reply address that the dialog shows.
3. Add your company's email domain and publish the DNS TXT record that the console shows, then press **Verify**. A domain sends nobody to the provider until its record is verified.
4. Sign out, and sign in with a company email address. The console sends you to your provider and back.

You can check a new provider before you rely on it. The API offers a test sign-in that records what the provider returned and signs nobody in.

## What success looks like

A person types their work email on the sign-in page, lands on your provider's page, signs in with whatever your provider requires, and arrives in the console. Their first sign-in creates their account and, if you set group rules, places them in the right teams. If anything fails, the person sees one message, "sign-in refused", whatever the cause, and the reason goes to the log.

## What skipping it costs

Without a provider, people sign in with a password stored in Ops AI, and a leaver has to be removed by hand in two places. Your provider's multi-factor rules do not apply to those passwords.

## What happens during a sign-in

<!-- site: sequence caption="Signing in through your identity provider: Ops AI never sees the person's password" -->
1. **Person → Console**: Enters a company email address
   - The email's domain picks the organisation and its provider.
2. **Console → Identity provider**: Sends the person to sign in
   - OIDC uses the authorization code flow with PKCE. SAML requests can be signed when you give Ops AI a key.
3. **Person → Identity provider**: Signs in with their work account
   - Multi-factor authentication is your provider's. Ops AI asks the provider to sign the person in, and the provider applies its own rules.
4. **Identity provider → Platform**: Returns a signed answer
   - The platform checks the signature, the issuer, the nonce and the email domain. SAML answers must be signed, and encrypted assertions are supported.
5. **Platform → Console**: Starts a session of up to 8 hours
   - The one-time code the browser carries becomes a session only in the browser that started the sign-in.

## Who gets an account, and which role

- A person's first sign-in through the provider creates their account.
- A provider's email address never opens an account that already exists. A person who already has an account adds the provider from their own signed-in session, or signs in from their invitation. Otherwise the sign-in ends with a "link required" message.
- A provider can name the team where new people land and the role they get. A first sign-in can give Chat user, Viewer, Builder or Reviewer, and never Admin.
- Group rules add people to teams with a role according to the groups the provider reports. With "remove when missing" on, a membership that a group gave ends when the person leaves the group.
- Sign-in started from the provider's own app portal, such as an Ops AI tile, is accepted for a provider that allows it.

## Sessions and approvals

- A session lasts up to 8 hours. The access token inside it lives 15 minutes and is renewed with a refresh token that works once. If someone presents a refresh token a second time, Ops AI ends the session and records it in the audit log.
- A sensitive approval can ask for a fresh sign-in. The approver goes through the provider again, which is asked to request credentials, and must come back as the same person. The sign-in counts for five minutes.
- Invitations are links that work once and expire after seven days.

## Passwords

Passwords work where the workspace has no sign-in provider, or where a password provider is enabled. Each password must be at least 12 characters and is stored as a salted PBKDF2-SHA256 hash with 600,000 iterations. After five wrong passwords in 15 minutes the person is locked out for 15 minutes, and the right password is refused during that time. Wrong passwords at sign-in and at step-up count together. A reset link is emailed only to a person who could sign in with a password, is valid for an hour, and ends every session the person had when it is used.

## Settings

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Sign-in providers and domains | Which provider serves which verified email domain | None: passwords only | A Security admin, in Settings › Security › Sign-in |
| Group rules | A provider group adds its members to a team with a role, never Admin | No rules | A Security admin, through the API on the provider |
| Company sign-in required | People on a verified domain sign in only through the provider. Up to three named Security admins keep a password as a break-glass way in. Each use is audited and the Security admins are told | Off | A Security admin, in Govern › Policies. Naming the break-glass admins is done through the API |
| Step-up on every approval | Every approver signs in again before deciding | Off: only operations that ask for it | A Security admin, in Govern › Policies |
| Invitations | Invite people by email with a single-use link | Not applicable | A team admin, in Govern › Access |

## What is not built yet

- SCIM provisioning is planned. Until then, accounts are created at first sign-in and group rules are applied at each sign-in. Ops AI does not ask your provider again during a session, so a person you remove at the provider keeps their session for up to 8 hours. To cut access sooner, remove their roles in **Govern › Access**, which applies on their next request.
- Group rules, the test sign-in and break-glass accounts are set through the API today, and the console does not edit them yet.

## Next

<!-- site: cards -->
- **[Access, approvals and audit](access-approvals-and-audit.md)**: What each role may do once signed in.
- **[Tenancy and isolation](tenancy-and-isolation.md)**: How teams and organisations are kept apart.
- **[API keys and the HTTP API](../reference/http-api.md)**: How scripts and services sign in.
