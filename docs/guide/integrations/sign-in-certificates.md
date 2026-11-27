# Sign in with a certificate

Status: current.

Banks often forbid shared client secrets. An app registration has to prove itself with a certificate whose private key the
bank controls, and some APIs also require mutual TLS. If the only choice were a client secret, a bank's security team
would block the integration. Ops AI supports three certificate sign-ins and keeps the key sealed, so no person, tool or
model can read it back.

## Set it up

You need the certificate and its private key as PEM text, from your certificate authority or security team, and the matching
public certificate registered at the app.

<!-- site: steps -->
1. **Open the app's sign-in.** Turn the app on in **Data Gateway › Apps**, or open its **Auth configs** tab.
2. **Pick the certificate option** in the Connect window (see the table below), and paste the certificate and its private
   key in PEM format. The key must have no password.
3. **Save.** Ops AI refuses a signing key that does not belong to its signing certificate.
4. **Check the account.** The account's API record carries the certificate's SHA-256 thumbprint, its subject, its expiry and a flag for expiry within
   30 days. The console does not show these yet, and the key is never shown.

## The options

| Option | What it does | You give | Typical use |
|---|---|---|---|
| OAuth app proves itself with a certificate (under **More settings**, set **How the client is sent** to private_key_jwt) | Every token request, refresh and sign-in carries a client assertion signed by your key, in place of a client secret | Client ID, signing certificate, signing key | Microsoft Entra app registrations at banks |
| Signed service account (JWT bearer) | Ops AI asks for a token with a JWT signed by your key, and signs a new one when it expires. No person signs in | Client ID (the issuer) and signing key. Optionally the certificate, a subject, an audience, and whether scopes go in the form or the claim | DocuSign (the integration key, with a user ID as subject) and Google service accounts |
| Client certificate (mutual TLS) | Presents your certificate on the TLS handshake of every call, together with any of the kinds above or a key | Client certificate, client key, and optionally a trusted CA | APIs on a private network that require mutual TLS |

The signing pair and the TLS pair are kept apart, so a signing key is never offered on a TLS handshake.

## Check the certificate on the account

The account reads **Connected**. The API record shows the thumbprint and expiry of the certificate you pasted, and flags it 30
days before it expires. Once it expires, every call from that account stops until someone pastes a new pair, so
put the renewal date in the calendar of whoever owns the certificate.

## What fails, and how it reads

| Case | What happens |
|---|---|
| The signing certificate has expired | Ops AI refuses before any token request, with the message "the signing certificate expired on <date>". The account asks to be connected again |
| The app refuses the assertion, for example because of a different key or a replay | The sign-in fails and names the app's host and error. It is never retried with a secret |
| The TLS handshake is refused | The call fails as a TLS failure and names the host |

## Keys and renewals

- Keys are RSA (RS256) or P-256 (ES256). Any other key is refused.
- Ops AI does not renew certificates. Renew at your certificate authority, then paste the new pair. The 30-day warning is
  the reminder.

## Next

<!-- site: cards -->
- [Sign in with OAuth](sign-in-oauth.md): team and personal sign-in, and your own OAuth app.
- [SharePoint and OneDrive](sharepoint.md): an Entra app that can use a certificate.
