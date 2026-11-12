# The console shows one area of pages at a time, chosen from the top bar

Status: draft. Id: `uc-723`. Service: `console`. Layers: ui.

The sidebar lists the pages of one area (Work, Build, Data or Govern) and the top bar switches areas, with one dropdown
on a phone. A person is offered a page exactly when they hold the cell its service checks, so the area control shows only
when two or more areas are offered. Design: the console areas design page, acceptance criteria section.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin, a builder, a reviewer and a viewer each see the areas and pages their cells open, and no listed page refuses them | ui | 1 | 1 |
| S2 | A person who only chats sees no area control and lands on Chat; a person in two teams sees what each team opens | ui | 2, 3 | 2 |
| S3 | A person switches area with a chord, search or a link, and the sidebar follows the page | ui | 4, 5, 6, 8 | 4 |
| S4 | The area a person last used is theirs alone | ui | 7 | 7 |
| S5 | On a phone, in a folded sidebar and from the keyboard the control still works | ui | 9, 10, 11 | 9 |
| S6 | While cells load or fail the sidebar says so; old addresses and Settings keep working | ui | 12, 13, 14 | 12 |

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in | `withUiStack(..., { platform: true, demo: true })` |
| Priya, James, Maya, Ravi, Wanjiru (admin of every team), and the fixtures Lena (chat only) and Tomas (builder in Operations, chat user in Platform) | `services/platform-service/seed/people.json`, password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya, Wanjiru, James, Maya and Ravi each sign in and open every row of every area | Four areas each; Govern holds what their cells open and nothing more (Background only for Wanjiru, who administers every team); no page answers 403 |
| 2 | Lena signs in, at 1440 and 390 | Lands on /chat; no area control; sidebar is New chat and All chats; `/` goes to /chat; /agents shows the page's own refusal with the sidebar unchanged and no area lit; the chord does nothing |
| 3 | Tomas picks Build, switches to Platform and back | In Platform no control and only chat rows; back in Operations the areas return |
| 4 | Priya on /cases presses the Build chord, then the Work chord | Build's first row opens with Build lit; Work returns to /cases, the last page she visited; search still opens |
| 5 | The chord with the chat composer focused, and with search open | Nothing changes |
| 6 | Search for "knowledge"; Ravi searches "activity" | Each page once, grouped by area; the pick lights Data; Ravi is offered no Activity |
| 7 | James picks Build, signs out; Priya signs in, picks Govern, signs out; James, then Priya sign in again | Priya starts on Work, James returns to Build, Priya to Govern |
| 8 | Priya opens /deployments, /prompt-blocks, /sources, /wiki, /connect, /reviews/all | Each lights its area and draws a trail; /connect redirects to /channels/mcp, so it lights Build |
| 9 | At 390 (the sheet is closed, so the page is ready when the area button has drawn) | One 44 px button replaces the control; a pick opens that area and the menu closes; the sheet lists only that area; picking a row closes it |
| 10 | At 1024 on Tool calls; at 1440 with the sidebar folded | No sideways scroll, no cut label; the four areas stay; on /chat the area is the one she was last in (Govern), as New chat has no area of its own |
| 11 | Keyboard and screen reader | One group named Area, one pressed item, arrows and Enter pick, a click on the lit item keeps it lit |
| 12 | Cells held back, then refused | Skeleton rows and no control; then "Pages unavailable" with Try again, which loads the rows |
| 13 | Priya opens Settings, then Back | The settings sidebar with Govern lit; Back returns to the area |
| 14 | Old addresses | /logs/tool-calls, /settings/policies and /account each answer one 307; Policies is at /policies |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-723-ui.mjs` | failing |

## Non-vacuous check

Step 4 presses the Build chord on /cases and expects Build's page with Cases gone from the sidebar, and the Work chord
to return to /cases; today the chords switch teams and the sidebar never changes. Step 1 fails on today's console, where
the area control does not exist.
