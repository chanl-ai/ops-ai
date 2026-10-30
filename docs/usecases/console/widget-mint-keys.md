# A builder issues and revokes a widget's mint key

Status: current. Id: `uc-116`. Service: `console`. Layers: ui. Card: an earlier change.

The bank's server starts an embedded chat's session for the person signed in to the intranet. It does that with a mint
key that belongs to one embed and can do nothing else. A builder of the agent's team creates the key from the embed's
row on the agent's Channels tab; the secret is shown once, because only its hash is kept. Revoking it stops the
server minting at once. A viewer sees the embeds and no key controls.
Design: [embedded chat](../../architecture/embedded-chat.md); guide: [embedding the chat](../../console/embedding-the-chat.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| James (builder) and Ravi (viewer) on team_ops | platform-service dev seed |

The script starts the stack with platform sign-in on the scripted model, creates and publishes an agent and makes an
embed for `http://127.0.0.1:4611` through the API.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens the embed's Mint keys, presses Create key with no name, then names it Intranet server | The name error sits under Name, marked invalid; then 201, the secret `wk.<tenant>.<key id>.<secret>` is shown, and the list shows the key as never used |
| 2 | The bank's server mints a session with the secret; James closes and reopens the dialog | 201; the reopened dialog does not show the secret, and the key reads as used |
| 3 | James presses Revoke, cancels, then revokes | Cancelling leaves the key working; the revoke answers 200, the key reads Revoked, and the same secret answers 401 `widget_key_invalid` |
| 4 | Ravi opens the same Channels tab | The embed is listed with no Mint keys button |

## Run

`make usecase-test UC=uc-116 LAYER=ui`
