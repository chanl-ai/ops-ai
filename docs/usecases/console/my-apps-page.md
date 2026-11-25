# My apps is a page of its own, the same for an admin and a member

Status: draft. Id: `uc-769`. Service: `console`. Layers: ui.

Every person who can chat has My apps first in Work, under New chat, at `/work/apps` outside Settings. It has no Mine
and Team setup switch, each card opens the app's own page at `/work/apps/<id>`, and the old Settings address lands on it.
An admin sees Connect wherever the person's own sign-in is the next step, as a member does. Where the team has not set
an app up, an admin is offered the setup on the card and a member reads who can do it.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in | the ui harness with `platform: true, demo: true` |
| An admin and a member | Priya Shah (admin) and James Richardson (builder) in Operations (`services/platform-service/seed/people.json`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya opens the old address `/settings/account/connectors` | She lands on `/work/apps`, titled My apps, with no Mine / Team setup switch and no "connectors" in the title or the empty text |
| 2 | She reads the sidebar at 1440 | My apps is the first row of Work after New chat |
| 3 | She opens the first card | The address is `/work/apps/<id>`, the page is titled with the app and offers its sign-in action |
| 4 | Where an app needs her own sign-in, she reads its card | The action is Connect, Add key or Sign in again, never Add an auth config |
| 5 | James walks steps 1 to 4 | The same page, the same cards; where the team has not set an app up, one line says who can, and never names James |
| 6 | Both walk at 390 | Nothing overflows sideways on the list or the app page |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `scripts/test-uc-769-ui.mjs` | draft |

## Non-vacuous check

Step 4: with the old action table back, an admin's card for an app that needs her own sign-in reads Add an auth config,
so the check fails. Step 1: with the redirect removed, `/settings/account/connectors` shows its own page, so the final
address is not `/work/apps`.
