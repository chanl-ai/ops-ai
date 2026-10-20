# A bank's server mints a widget session, and the chat's approval is decided through Reviews

Status: current. Id: `uc-117`. Service: `agents-service`. Layers: api. Card: c-131.

The bank's server mints a 15-minute session for the signed-in person with the deployment's own mint key; a team API
key, another deployment's key and a revoked key mint nothing. The embed app's server reads the deployment's public
config (agent, origins, paused) with no team or tenant in it. The page starts the thread with the first message, and
the agent drafts a wire hold that waits for approval. Another person's session cannot read or decide that conversation.
The page has no route to decide it, since a widget session holds no reviewer role; an approver decides it in Human
Tasks and the widget conversation resumes.
Design: [embedded chat](../../architecture/embedded-chat.md); guide: [embedding the chat](../../console/embedding-the-chat.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |

The script starts agents-service on the scripted model with dev sign-in and the fixture seed (Fraud Investigator with
`place_wire_hold`).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James makes two deployments and a mint key for each; the bank's server mints with the first key, then with a team key and with the second deployment's key | 201 with a session; 403 `widget_key_required`; 403 `widget_key_other_deployment` |
| 2 | The embed app reads `GET /v1/widget/{id}/config?tenant=local` with the intranet's Origin, then with no Origin | 200 with the agent name, the intranet origin and paused false, no team; then 403 |
| 3 | The page starts a thread and sends a request to hold a wire | The stream carries the approval widget |
| 4 | Another person's session reads the thread; the asker posts a decision from the page | 404; 404 or 405, as no such route exists |
| 5 | An approver approves it in Reviews; the page reads the thread | 200; `place_wire_hold` succeeded and the last message is the agent's |
| 6 | James revokes the key; the server mints with it | 200; 401 `widget_key_invalid` |

## Run

`make usecase-test UC=uc-117 LAYER=api`
