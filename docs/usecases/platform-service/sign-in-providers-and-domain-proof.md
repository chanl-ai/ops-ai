# A Security admin sets a sign-in provider, and its domain routes sign-in only once proven by DNS

Status: current. Id: `uc-213`. Service: `platform-service`, console. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; run the ui layer with `ISOLATED=1` |

The scripts start platform-service in dev on the run's database with the dev seed (Wanjiru Kamau, workspace admin
and Security admin in every team; James Richardson, builder), sign-in URLs, an OIDC client secret named `uc-oidc`, and
the local fake identity provider with its fake DNS on the same port over UDP (`OPS_SIGNIN_DNS_SERVERS`). The ui layer
adds the console signed in through platform-service. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James reads the secret names, or verifies a domain | 403 |
| 2 | Wanjiru adds an OIDC provider for a new domain (ui: Settings > Sign-in, Add provider) | Saved; the domain is listed as pending with its TXT record `ops-ai-verify=<token>` |
| 3 | A SAML provider with a certificate that is not one (ui) | Refused; the server's reason shows under the certificate field |
| 4 | The sign-in page asks how an email on the pending domain signs in | No SSO; an SSO start is refused (400) |
| 5 | Verify with nothing published, then with a wrong value | 422 `domain_unverified`, naming the values DNS held |
| 6 | Publish the record at the fake DNS and verify | Verified; the email now signs in through Northfield SSO |
| 7 | Save the provider again; list the same domain on a second provider | Still verified; 409 `domain_taken` |
| 8 | Reload the page; narrow it to 400 px; James opens it (ui) | Provider and verified domain still there; no page scroll; James is told the Security team sets sign-in |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-213-api.py` | passing |
| ui | `platform-service/scripts/test-uc-213-ui.mjs` | passing |

## Non-vacuous check

With `platform_signin_domain` returning unverified domains and the TXT check skipped, the pending domain starts an SSO
sign-in and a squatted claim blocks the owner, and the domain tests fail
(`.codeloop/evidence/195/red-domain-verification.txt`).
