# Sign in with a certificate

Status: current.

Banks often forbid shared client secrets: an app registration must prove itself with a certificate whose private key
the bank controls, and some APIs also require mutual TLS. Ops AI supports three certificate sign-ins, and keeps the key
sealed so no person, Tool or model can read it back.

## Set it up

<!-- site: steps -->
1. **Turn the App on** in **Data Gateway › Apps**, or open its **Auth configs** tab.
2. **Pick the certificate option** in the Connect window (below) and paste the certificate and its private key, in PEM.
3. **Save.** A key that does not belong to its certificate is refused, naming both.
4. **Check the account.** Its row shows the certificate's SHA-256 thumbprint, subject and expiry, and warns when it
   expires within 30 days. The key is never shown.

## The options

| Option | What it does | You give | Typical use |
|---|---|---|---|
| OAuth app proves itself with a certificate | Every token request, refresh and sign-in carries a client assertion signed by your key, in place of a client secret | Client ID, signing certificate, signing key | Microsoft Entra app registrations at banks |
| Signed service account (JWT bearer) | Ops AI asks for a token with a JWT signed by your key, and signs a new one when it expires. No person signs in | Client ID (the issuer), signing key; optionally certificate, subject, audience, and whether scopes go in the form or the claim | DocuSign (the integration key, a user ID as subject) and Google service accounts |
| Client certificate (mutual TLS) | Presents your certificate on the TLS handshake of every call, with any of the kinds above or a key | Client certificate, client key, and optionally a trusted CA | APIs on a private network that require mTLS |

The signing pair and the TLS pair are kept apart, so a signing key is never offered on a TLS handshake.

## What fails, and how it reads

| Case | What happens |
|---|---|
| The signing certificate has expired | Refused before any token request: "the signing certificate expired on <date>". The account asks to be connected again |
| The app refuses the assertion (another key, a replay) | The sign-in fails naming the app's host and error. It is never retried with a secret |
| The TLS handshake is refused | The call fails as a TLS failure, naming the host |

## Limits

- Keys are RSA (RS256) or P-256 (ES256). Any other key is refused.
- Ops AI does not renew certificates. Renew at your CA, then paste the new pair; the 30-day warning is the reminder.

## Next

<!-- site: cards -->
- [Sign in with OAuth](sign-in-oauth.md): team and personal sign-in, and your own OAuth app.
- [SharePoint and OneDrive](sharepoint.md): an Entra app that can use a certificate.
