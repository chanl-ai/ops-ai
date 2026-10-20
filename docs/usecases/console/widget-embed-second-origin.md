# An agent embedded on an intranet page answers from another origin

Status: current. Id: `uc-109`. Service: `console`. Layers: ui. Card: c-118.

A builder embeds a published agent on the bank's intranet from the agent's Channels tab: a name and the exact page
origins. The console shows the page code for the embed loader (`/embed/v1.js`) with the deployment, and nothing secret.
The intranet page loads it, its `getSession` trades the person's SSO token for a 15-minute session bound to that page's
origin, and the person chats in the embed app's frame. A page on an origin the deployment does not list cannot start
the chat. The first widget script, `/widget/v1.js`, answers 410 Gone since c-224.
Design: [chat](../../console/chat.md); server routes in c-117; interview: c-076 Q1-Q6.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| James (builder) and Maya on team_ops | platform-service dev seed |

The script starts the stack with platform sign-in on the scripted model and the embed app, creates and publishes an agent, and serves the
demo intranet (`services/agents-service/demo/intranet-page`) on two `127.0.0.1` ports; the console is on `localhost`.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens the agent's Channels tab, presses Embed on a page, names it and adds the intranet origin | 201; the dialog shows the embed loader's page code with the deployment id and `OpsChat.init`, and no key |
| 1b | James presses Create embed with nothing filled in, then with a name and no origin | the name error sits under Name and the origin error under the origins, each field marked invalid; the origins placeholder starts with "e.g." |
| 1c | At 400px wide James opens a new agent's Channels tab | the empty state and its button sit inside the viewport |
| 1d | James opens the Snippet, then presses Pause, cancels, presses Pause again and confirms, then presses Resume and confirms | Snippet carries `aria-expanded` and `aria-controls` for the row it opens; the confirm names the intranet origin; cancelling sends no PATCH; both confirms answer 200 |
| 2 | Maya opens the intranet page, whose `getSession` posts her SSO token to `/v1/widget/{id}/session`, opens the chat and asks a question | The session is minted for the intranet origin (201); the reply appears in the chat frame; `GET /widget/v1.js` answers 410 |
| 3 | The same page served from an origin the deployment does not list loads the chat | The loader draws nothing and reports `origin_not_allowed`; the session request answers 403 `origin_not_allowed` with no CORS header |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-109-ui.mjs` | passing |

## Non-vacuous check

Step 3 is the refusal: removing the origin check in `widget_sessions.allowed` lets the unlisted page start a session and
step 3 fails. `apps/console/src/lib/widget-snippet.test.ts` fails when the snippet or the widget script carries a key.
