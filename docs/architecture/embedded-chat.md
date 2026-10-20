# Embedded chat

Status: current for the server side, 2026-10-17. Deployments, sessions, origins, limits, mint keys (with expiry and an audit) and the
public config read are built, and so are the loader (`/embed/v1.js`) and the embed app (`apps/embed`).

A bank can put an Ops AI agent's chat on its own web pages, such as an intranet. The embedded chat is the same chat as
the console (sources, answer widgets, tool status, approvals) and is served from the bank's own Ops AI deployment.

## Design

| Concern | Decision |
|---|---|
| Rendering | A small embed app in an iframe on the Ops AI host, launched by a thin loader script on the bank's page |
| Who the person is | The bank's server, which already knows who is signed in, mints a 15-minute session for that person with the widget's own mint key, which can do nothing else; the page holds only the session |
| Signed out | No anonymous chat: the chat shows a Sign in button that runs the page's own sign-in |
| Isolation | The conversation never leaves the iframe; the page receives open, close, unread and error events only |
| Framing | Only origins listed on the deployment may frame the app (`frame-ancestors`), and only they may use its sessions |
| Messages between page and iframe | Both sides check the sender's window and origin, and post to one exact origin |
| Limits | 10 messages a minute per person and 60 per deployment; pausing the deployment stops every open conversation |

## The embed app

`apps/embed` is a small Next app that draws the console's own chat components. Its `@/*` imports resolve into
`apps/console/src`, and `@/lib/api` resolves to `apps/embed/src/widget-api`, which talks only to `/v1/widget/{id}` with
the session the loader passed; `pnpm --filter @ops-ai/embed check:bundle` fails if the console's API client or mock
reaches the bundle. The app serves `/embed/{deployment}` and routes `/v1/*` and `/embed/v1.js` to agents-service, so
the loader, the chat page and the API share one host; a call from the frame comes from an origin `Settings.embed_origins`
(`OPS_EMBED_ORIGINS`) lists and speaks for the bank page its session was minted for; no request header can add one.

## Routes

All in agents-service `api/routers/widget.py`.

| Route | Caller | What it does |
|---|---|---|
| `POST /v1/widget-deployments/{id}/sessions` | The bank's server, with the deployment's mint key | Mints a 15-minute session for one person on one listed origin |
| `GET /v1/widget/{id}/config?tenant=` | The embed app, forwarding the framing page's origin, or a server with the mint key | Agent name, deployment name, paused, starter questions and the origins it builds `frame-ancestors` from; no team or tenant; 403 for any other caller, 404 for an unknown deployment |
| `POST /v1/widget/{id}/threads`, `GET /v1/widget/{id}/threads/{tid}`, `POST .../messages` | The page, with `X-Widget-Session` | Start, read and continue the person's own conversations |

Every page route answers 404 for a conversation that is not the session person's, or not this deployment's. The page
has no route to decide an approval: a widget session holds no reviewer role, so an approver decides it in Human Tasks
and the widget conversation resumes. Form widgets take no submit from the embed yet.

## Identity options

Three patterns are common for identifying a signed-in person to an embedded chat.

| Pattern | The bank's server | The page holds | Expiry and replay | What breaks |
|---|---|---|---|---|
| Hash of the user id with a shared secret | Computes the hash per page view | User id and hash | None: a copied hash works until the secret rotates | Two copies of one secret drift apart and every identified visit is refused |
| A token the bank signs (JWT with a key id) | Signs a short token per page view | The token | Minutes, set by the bank; audience and origin can be bound | A wrong clock or an expired key; rotation by key id |
| A session minted server to server | Calls the chat provider with a key per page view | A short session | Minutes, set by the provider; bound to origin and person | The call from the bank's server to Ops AI must succeed |

Ops AI uses the third today. For banks whose sign-in already issues signed tokens, the planned addition is the second:
the bank registers a public key set for the deployment, signs a short token for the person with its private key, and Ops
AI verifies it and exchanges it for the same 15-minute session. Ops AI then holds no secret that can create identities,
and the bank rotates keys by key id.

## Reading further

Builders: `docs/console/embedding-the-chat.md` gives the steps, calls, events and errors.
