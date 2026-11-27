# Chat on your own pages

Status: current. The server side, the loader and the embed app are built and checked end to end on a sample page. The
installer does not run the embed app yet; adding it to the Compose and Kubernetes installs is planned.

If your people spend their day in an intranet or a portal, you can put your agent on that page, so they can ask it a
question without leaving their work.

## People will not leave the page they work in to ask a question

A bank's staff work in the intranet, and a claims team spends its day in its case portal. If the agent lives only in the
Ops AI console, people rarely open it, and their questions go back to colleagues. Embedding a chat carries its own risk,
because a chat that anyone outside it can read exposes conversations from the very first one.

With Chat on your own pages, the agent sits behind a launcher in the corner of the page. The launcher opens the same chat
people use in the console, with sources, answer widgets, tool cards and approval cards, and an approver decides those
approvals in Human Tasks. The chat runs in an iframe served by your own Ops AI deployment, so nothing else on the page can
read the conversation. Each person is identified by a short session that your server mints for them.

## Four steps to a working chat

<!-- site: steps -->
1. **Create a widget deployment** for the agent and list the page origins that may embed it.
2. **Mint a session on your server** for the person who is signed in. The page never holds a key.
3. **Add the script tag** to the page.
4. **Try it** on a test page before you go live.

## How the pieces fit

| Piece | Where it runs | What it holds |
|---|---|---|
| Widget deployment | Ops AI | The agent, the allowed page origins, paused or not |
| The bank's session endpoint | The bank's server | The widget's mint key (never sent to the page) |
| Loader script | The intranet page | Nothing secret: the deployment id and the current 15-minute session |
| Embed app | An iframe from the Ops AI host | The conversation; it talks to Ops AI with the session |

## 1. Create a widget deployment

In the console, open the agent's **Channels** tab and choose **Embed on a page**. You can also start from Deployments >
New deployment > Chat widget, which asks you to pick the agent. Then list every page origin that will embed the chat, for
example `https://intranet.harborpine.example`. Only an exact origin is accepted, meaning the scheme, host and port, with
no wildcards and no paths. The console then shows a snippet that contains steps 2 and 3 below, with the deployment and
tenant already filled in.

If you work through the API instead, call `POST /v1/widget-deployments` with `{ name, agentId, origins }`. The response
contains the deployment id (`wd_…`).

Pausing the deployment stops every embedded conversation at once. New sessions are refused with 409 `widget_paused`, and
so is every request from a session that is already open.

## 2. Mint a session on your server

Your server, here the bank's, already knows who is signed in to the intranet. It asks Ops AI for a session for that
person using the widget's **mint key**, and then passes only the session to the page. A mint key can mint sessions for one
widget deployment and can do nothing else. If your server sends a team API key or a person's token here instead, the
request is refused.

A builder or admin of the widget's team creates the key with `POST /v1/widget-deployments/{id}/keys` and
`{ "name": "Intranet server" }`. The response carries the secret only once (`wk.<tenant>.<key id>.<secret>`), because
Ops AI keeps only its hash, so store it as soon as you receive it. You can list keys with
`GET /v1/widget-deployments/{id}/keys` and revoke one with `POST /v1/widget-deployments/{id}/keys/{keyId}/revoke`.

In the console, the same controls sit on the agent's Channels tab: open the embed's row and choose **Mint keys**.
Builders of the agent's team can create and revoke keys there, while viewers see no key controls.

```http
POST https://ops.harborpine.example/v1/widget-deployments/wd_123/sessions
Authorization: Bearer wk.<tenant>.<key id>.<secret>
Content-Type: application/json

{ "email": "j.richardson@harborpine.example", "name": "James Richardson", "origin": "https://intranet.harborpine.example" }
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

Here is a minimal endpoint in Node. The same shape works in any framework.

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
<script src="https://ops.harborpine.example/embed/v1.js" async></script>
<script>
  function startChat() {
    OpsChat.init({
      deployment: 'wd_123',
      tenant: 'harborpine',
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

The page holds no key. When it starts, the loader first reads the deployment's config. If the page's origin is not on
the deployment's list, that read is refused, nothing is drawn, and the `error` event reports `origin_not_allowed`.
Otherwise the loader draws the launcher, creates the iframe (`/embed/{deployment}` on the same host) the first time
someone opens it, and passes the session to it. `getSession` may also return the session as a plain string, in which
case the loader refreshes it after 14 minutes.

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

The host page never receives message text, because the conversation stays inside the iframe.

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
| Only listed pages can frame the chat | The embed app answers with `Content-Security-Policy: frame-ancestors` built from the deployment's origins; with no listed page, `'none'` |
| Messages between page and iframe cannot be forged | Both sides check `event.origin` and `event.source` and post to one exact origin, never `'*'` |
| A copied session expires soon | 15 minutes, bound to the deployment, the origin and the person |
| No empty conversations | A thread is created on the first message, not on open |

## 7. Try it before you go live

<!-- site: steps -->
1. Create a widget for an agent on a test install, listing the origin of the page you will test from, and create its
   mint key.
2. Serve a test page from that origin with the script tag above, and a session endpoint that calls step 2's route with
   the mint key.
3. Open the page. The launcher should appear, and opening it should show the agent's greeting. Then check that a page
   on an origin you did not list loads nothing, and that the browser console shows no message text reaching the page.

## How you know it works

Once the embed is working, a person opens the intranet page, sees the launcher and chats with the agent, with sources and approval cards. A page on
an origin you did not list loads nothing, and the browser console shows no message text reaching the host page.

## If you do without it

Without the embed, people keep taking their questions to colleagues instead of the agent. A hand-built embed brings a
different problem: the host page can read the conversation, and a leaked key lets anyone chat as anyone.

## Where to go next

<!-- site: cards -->
- **[Chat and channels](../guide/ops-assistant.md)**: what the chat does once it is open.
- **[Agents](../guide/agents.md)**: publish the agent the widget serves.
- **[Security](../security/README.md)**: sign-in, isolation and audit for a security review.
