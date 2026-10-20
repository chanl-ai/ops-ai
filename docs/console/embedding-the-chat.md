# Embedding the chat on a bank page

Status: current, 2026-10-17. The server side, the loader and the embed app (`apps/embed`) are built; uc-119 drives them
on a sample bank page.

A bank team puts its Ops AI agent on an intranet page: a launcher in the corner opens the same chat people use in the
console, with sources, answer widgets, tool cards and approval cards (an approver decides them in Human Tasks). The chat
runs in an iframe served by the bank's own Ops AI deployment, so nothing on the intranet page can read the conversation,
and the person is identified by a short session the bank's server mints for them.

## How the pieces fit

| Piece | Where it runs | What it holds |
|---|---|---|
| Widget deployment | Ops AI (agents-service) | The agent, the allowed page origins, paused or not |
| The bank's session endpoint | The bank's server | The widget's mint key (never sent to the page) |
| Loader script | The intranet page | Nothing secret: the deployment id and the current 15-minute session |
| Embed app | An iframe from the Ops AI host | The conversation; it talks to agents-service with the session |

## 1. Create a widget deployment (Built)

In the console, open the agent's **Channels** tab and choose **Embed on a page** (or Deployments > New deployment > Chat
widget, which asks for the agent), and list every page origin that will embed it, for example
`https://intranet.northfield.example`. The snippet it then shows is steps 2 and 3 below with the deployment and tenant
filled in (c-224). Only an exact origin is accepted (scheme, host and port; no wildcards and
no paths). The API is `POST /v1/widget-deployments` with `{ name, agentId, origins }`; it answers the deployment id
(`wd_…`).

Pausing the deployment stops every embedded conversation: new sessions are refused with 409 `widget_paused`, and so is
every request of a session already open.

## 2. Mint a session on the bank's server (Built)

The bank's server already knows who is signed in to the intranet. It asks Ops AI for a session for that person, with the
widget's **mint key**, and hands only the session to the page. A mint key mints sessions for one widget deployment and
does nothing else; a team API key or a person's token is refused here.

Create the key with `POST /v1/widget-deployments/{id}/keys` and `{ "name": "Intranet server" }` as a builder or admin of
the widget's team. The answer carries the secret once (`wk.<tenant>.<key id>.<secret>`); only its hash is kept. List
keys with `GET /v1/widget-deployments/{id}/keys` and revoke one with `POST /v1/widget-deployments/{id}/keys/{keyId}/revoke`.
In the console: the agent's Channels tab, the embed's row, **Mint keys**. Builders of the agent's team create and
revoke keys there; viewers see no key controls.

```http
POST https://ops.northfield.example/v1/widget-deployments/wd_123/sessions
Authorization: Bearer wk.<tenant>.<key id>.<secret>
Content-Type: application/json

{ "email": "j.richardson@northfield.example", "name": "James Richardson", "origin": "https://intranet.northfield.example" }
```

```json
{ "success": true, "data": { "session": "<opaque>", "expiresIn": 900 } }
```

| Rule | Why |
|---|---|
| Only the widget's mint key mints; a team API key or a person's token gets 403 `widget_key_required` | A team key can call every team API, and a person's token would let anyone act as anyone; the mint key can only vouch for a person in this one chat |
| A revoked or wrong key gets 401 `widget_key_invalid`; another widget's key gets 403 `widget_key_other_deployment` | A leaked key is stopped in one step and reaches no other chat |
| `origin` must be on the deployment's list | The session is bound to that origin and refused from any other |
| The session lasts 15 minutes and is not renewable | A copied session is useless soon; the loader asks the bank for a new one before it ends |
| Keep the key in the bank's secrets manager, never in the page | Anyone holding it can mint a session for any person in this chat |

A minimal endpoint (Node, any framework is the same):

```js
app.post('/api/ops-chat/session', requireIntranetLogin, async (req, res) => {
  const r = await fetch(`${OPS_URL}/v1/widget-deployments/${DEPLOYMENT}/sessions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${process.env.OPS_WIDGET_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: req.user.email, name: req.user.name, origin: INTRANET_ORIGIN }),
  });
  if (!r.ok) return res.status(502).json({ error: 'assistant unavailable' });
  res.json((await r.json()).data); // { session, expiresIn }
});
```

## 3. Add the script tag

```html
<script src="https://ops.northfield.example/embed/v1.js" async></script>
<script>
  function startChat() {
    OpsChat.init({
      deployment: 'wd_123',
      tenant: 'northfield',
      // Called on start, before the session ends, and after a 401; returns { session, expiresIn } or null when signed out.
      getSession: async () => {
        const r = await fetch('/api/ops-chat/session', { method: 'POST', credentials: 'include' });
        return r.ok ? await r.json() : null;
      },
      // Shown on the signed-out card's Sign in button; omit it and the card says to sign in to the intranet.
      onSignIn: () => location.assign('/login?next=' + encodeURIComponent(location.pathname)),
    });
  }
  window.OpsChat ? startChat() : window.addEventListener('ops-chat:load', startChat);
</script>
```

The page holds no key. The loader first reads the deployment's config; on a page whose origin the deployment does not
list, the read is refused, nothing is drawn and the `error` event says `origin_not_allowed`. It then draws the launcher,
creates the iframe (`/embed/{deployment}` on the same host) on first open, and passes the session to it. `getSession`
may also return the session as a string; it is then refreshed after 14 minutes.

## 4. Control it from the page

| Call | Does |
|---|---|
| `OpsChat.open()` / `OpsChat.close()` | Opens or closes the panel |
| `OpsChat.identify(session)` | Hands a session the page already has (instead of `getSession`), or `null` to sign the chat out |
| `OpsChat.on(event, handler)` / `OpsChat.off(event, handler)` | Subscribes to the events below |

| Event | Payload | When |
|---|---|---|
| `ready` | none | The iframe loaded and accepted a session |
| `open`, `close` | none | The panel opened or closed |
| `message` | `{ role, at }`, never the text | A message arrived; for an unread badge |
| `signed-out` | none | No session, or the bank's endpoint returned none |
| `error` | `{ code }` | One of the codes below |

The host page never receives message text: the conversation stays inside the iframe.

## 5. Errors

| Status and code | Meaning | What happens |
|---|---|---|
| 401 | The session ended or is not valid for this origin | The loader calls `getSession` once; if that returns `null`, or the new session ends again within seconds, the chat shows Sign in |
| 403 `origin_not_allowed` | The page's origin is not on the deployment | Nothing loads; add the origin in Widgets |
| 403 `widget_key_required`, 401 `widget_key_invalid` | Minting with something other than this widget's live mint key | Mint with the widget's mint key |
| 409 `widget_paused` | The deployment is paused | The chat says the assistant is paused |
| 429 `rate_limited` | More than 10 messages a minute for a person, or 60 for the deployment | The chat asks to wait; the error's `details.retryAfter` gives seconds |

## 6. Security properties

| Property | How |
|---|---|
| The page cannot read the conversation | The chat runs in a cross-origin iframe; events carry no text |
| Only listed pages can frame the chat | The embed app answers with `Content-Security-Policy: frame-ancestors` built from the deployment's origins (Built, `apps/embed/src/proxy.ts`); with no listed page to read the config for, `'none'` |
| Messages between page and iframe cannot be forged | Both sides check `event.origin` and `event.source` and post to one exact origin, never `'*'` (Built: the loader, `tests/loader/loader.browser.mjs`, and the frame, `apps/embed/src/frame.tsx`) |
| A copied session expires soon | 15 minutes, bound to the deployment, the origin and the person (Built) |
| No empty conversations | A thread is created on the first message, not on open (Built, uc-119) |

## 7. Test it locally

1. `make up AUTH=platform` (or `ISOLATED=1` for your own stack) and sign in to the console as an admin.
2. In **Widgets**, create a widget for an agent with origin `http://localhost:5500`, and create its mint key
   (`POST /v1/widget-deployments/{id}/keys`).
3. Serve a page on `http://localhost:5500` with the script tag above and a session endpoint that calls step 2's route
   with the mint key (`OPS_URL=http://127.0.0.1:8700`).
4. Open the page: the launcher shows; opening it shows the agent's greeting. Check an unlisted origin
   (`http://127.0.0.1:5500`) loads nothing, and that the browser console shows no message text reaching the page.
