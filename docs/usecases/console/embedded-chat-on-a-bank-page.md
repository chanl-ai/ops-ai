# A bank page shows the full chat through the loader and the embed app

Status: current. Id: `uc-119`. Service: `console`. Layers: ui. Card: an earlier change.

A bank's intranet page loads the loader from the Ops AI host and passes a session its own server minted with the
deployment's mint key. The chat opens in the embed app's iframe with the console's own components. The thread is made
by the first message. A drafted wire hold shows the console's approval card, waiting and without buttons; an approver
decides it in Human Tasks and the widget conversation carries on. A frame from another origin cannot sign the chat out,
the host page cannot read the conversation, a signed-out page gets a Sign in that runs its own login, and only the
listed page may frame the chat.
Design: [embedded chat](../../architecture/embedded-chat.md); guide: [embedding the chat](../../console/embedding-the-chat.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| James (team_ops builder) and Maya (team_ops approver) | platform-service dev seed |

The script starts the stack with platform sign-in, the scripted model and the embed app, makes a deployment of the
Fraud Investigator for `http://127.0.0.1:4621` with a mint key, and serves the bank page there and another origin on
4622.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open the bank page and the chat | The greeting and a footer naming the signed-in person; the loader's `ready` event; no thread created |
| 2 | Ask it to hold wire W-1 | One thread created; the approval card waits for the approving team, with no Approve or Reject |
| 3 | An approver approves it in Human Tasks; reopen the chat | 200; the conversation shows the hold placed |
| 4 | A frame from another origin posts a sign-out to every frame | Ignored: the composer stays and no `signed-out` event |
| 5 | The host page reads the frame and the loader | No document, no shadow root, no message text in page text or events |
| 6 | A page with no session opens the chat and presses Sign in | The signed-out card; the page's `onSignIn` runs |
| 7 | The chat page is requested from the listed page and from another | `frame-ancestors` names the bank page; `'none'` for the other |

## Run

`make usecase-test UC=uc-119 LAYER=ui`
