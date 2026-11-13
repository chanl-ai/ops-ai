# A new workspace can chat and write with no extra setup

Status: draft. Id: `uc-751`. Service: `platform-service` with models-service and tools-service. Layers: sdk, ui.

An admin creates a workspace (bootstrap on an install, or the dev seed on an empty database), signs in, adds the
company's model key, and an agent in chat answers and changes a record in a connected app. Nothing else is set first:
publishes go live at once, an app may call any public address, writes do not wait for a reviewer and approving asks
for no password. Each of those is a setting an admin turns on in Settings › Policies. A workspace created before keeps
the values it had.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A new workspace reads publish review `never` for its first team and new addresses `any_public` | sdk | 1 | 1 |
| S2 | Approvals and step-up read off in a new workspace | sdk | 2 | 2 |
| S3 | The first admin, with no model key, sees the setup card on the overview and it leads to Model providers | ui | 3 | 3 |
| S4 | After a key is saved the card is gone, and a chat answers and a write runs without waiting | sdk, ui | 4, 5 | 4, 5 |
| S5 | A workspace created before reads its old values: publish review `major`, new addresses `ask_security` | sdk | 6 | 6 |
| S6 | Turning an app on runs every call as the team's account; each person signing in stays a choice on the app's settings | sdk, ui | 7 | 7 |
| S7 | A built-in OAuth app connects with Ops AI's own client when the team brings none (`OPS_PLUGIN_CLIENTS`, filled from the deploy's secret store) | sdk | 8 | 8 |
| S8 | The invite dialog preselects Builder; Chat shows an admin the model setup; an empty templates list links to Connectors | ui | 9 | 9 |

## Preconditions

| Needs | How |
|---|---|
| A fresh database and the stack | `make up` without `KEEP_DATA=1` |
| A model key | the account's own OpenAI, Azure OpenAI or Anthropic key |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `make sdk-call CALL='ops.raw.platform.policies_get("publishReview")' AS=admin`, then `egressNewHosts` | Every area of the first team is `never`; `any_public` |
| 2 | The same for `appChanges` and `stepUp` | `{}` and `false` |
| 3 | Sign in as the admin at 1440 and 390 | The overview shows "Set up your AI model" with three steps; "Add a model key" opens Model providers. A member sees no card |
| 4 | Add the key on Model providers, back to the overview | No setup card |
| 5 | Ask an agent with a write tool to change a record | It answers and the write runs without a review |
| 6 | Steps 1 and 2 on a workspace created before this change | `{}` (each area `major`) and `ask_security` |
| 7 | Turn GitHub on from Connectors › Team setup without changing "Whose account", then `GET /v1/apps/plugin:opsai.github/accounts/{id}` | The window preselects the team account; the account reads `signIn: team`, so a member's first call needs no sign-in of their own |
| 8 | With `OPS_PLUGIN_CLIENTS` holding a client for the app, turn it on with no auth config of the team's own | The turn-on succeeds and sign-in uses Ops AI's client; with the variable empty it refuses with `client_missing` |
| 9 | Open Access › Invite, then Chat as the admin with no model key, then From a template in a team with no packs | Builder is selected; Chat shows "Set up your AI model" above the composer; the empty list says to turn an app on in Connectors, linked to `/data/connectors` |

## Not covered yet

A member sees no setup card before chatting: whether the account has a model key is readable only by an account admin
(models-service). A member is told to ask an admin when a reply is refused for the missing key (`provider_key_missing`).
The team-account default and the Builder preselection apply to every workspace's next turn-on and invite; accounts and
members made before keep what they hold.

Testing the key when it is saved and choosing which of the account's models chat uses need two models-service routes
that do not exist (test a key, list a provider's models).
