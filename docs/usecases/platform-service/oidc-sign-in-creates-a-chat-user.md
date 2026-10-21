# An OIDC sign-in creates a chat-only person once

Status: current. Id: `uc-161`. Service: `platform-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev on the run's database with the dev seed (tenant `local`, team `team_ops` with
Priya Shah admin, James Richardson builder, Ravi Menon viewer; team `team_security` with Sam Adeyemi admin; demo password
`northfield-demo`), its public and console URLs set, one OIDC client secret named `uc-oidc`, reset mail written to a
folder, and the local fake identity provider (`python -m ops_signin.fake_idp`) on the run's IdP port. No real
identity provider and no model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya invites Sam to team_ops as admin; Sam accepts as himself | Sam may now send new people to team_ops |
| 2 | Sam sets an OIDC provider for a new domain, first sign-in team team_ops as Chat user, and keeps passwords on | 200 twice |
| 3 | Ask how `new.teller@<domain>` signs in | `sso: {kind: oidc, label: Harbor & Pine SSO}` |
| 4 | The teller signs in at the provider and completes with the flow key | An `oidc` session, role `chat_user` on team_ops; only chat permissions; members list 403 |
| 5 | Sign in again | The same person; team_ops lists them once as a chat user |
| 6 | The provider vouches for an address outside its domains | `error=sign_in_refused`; nobody is made |
| ui | On the console, type the domain's email: the form becomes Continue with SSO naming Harbor & Pine SSO; continue | The fake provider sends the browser back and the console signs the teller in |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-161-api.py` | passing |
| ui | `platform-service/scripts/test-uc-161-ui.mjs` | passing |

## Non-vacuous check

`an email outside the provider's domains is refused`: with the domain check removed, a person is made for the
other domain and the check fails.
