# The console lists every area as an open sidebar section, and shows area tabs only when the install turns them on

Status: draft. Id: `uc-723`. Service: `console`. Layers: ui.

By default one sidebar lists every area the person may open as a section: Work (with Chat), Agent Builder, Data Gateway
and Governance, one link per page and nothing folded. The header trail and search still name the areas Work, Build, Data
and Govern. A person is offered a page exactly when they hold the cell its service checks, so a section with no page the
person may open is left out. An install that names `area_tabs` in `OPS_FLAGS` gets the area tabs instead: four buttons in
the top bar (one dropdown on a phone), and a sidebar that lists the picked area alone. Design: the console areas design
page, acceptance criteria section.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin, a builder, a reviewer and a viewer each see the sections and pages their cells open, all open, and no listed page refuses them | ui | 1 | 1 |
| S2 | A person who only chats sees only Work with Chat in it and lands on Chat; a person in two teams sees what each team opens | ui | 2, 3 | 2 |
| S3 | Every section is on screen at once, the page's row is lit in its own section, and search and old links land on the right row | ui | 4, 6, 8 | 4 |
| S4 | While cells load or fail the sidebar says so; old addresses, the trail and Settings keep working | ui | 12, 13, 14, 15 | 12 |
| S5 | With `area_tabs` on, the four area tabs return, a chord switches the sidebar to one area, and a phone gets one button | ui | 16 | 16 |

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in | `withUiStack(..., { platform: true, demo: true })`; step 16 runs a second stack with `OPS_FLAGS=area_tabs` |
| Priya, James, Maya, Ravi, Wanjiru (admin of every team), and the fixtures Lena (chat only) and Tomas (builder in Operations, chat user in Platform) | `services/platform-service/seed/people.json`, password `northfield-demo` |

## Steps and expected results

Steps 1 to 15 run with no flags; step 16 runs with `area_tabs` on. Step numbers are not reused, so some are absent.

| # | Step | Expected |
|---|---|---|
| 1 | Priya, Wanjiru, James, Maya and Ravi each sign in and open every row of the sidebar | Sections Work, Agent Builder, Data Gateway, Governance, in that order; Governance holds what their cells open and nothing more (Background only for Wanjiru, who administers every team); no row hides pages behind an arrow; no area control; no page answers 403 |
| 2 | Lena signs in, at 1440 and 390 | Lands on /chat; the only section is Work holding Chat; New chat above it; no area control; `/` goes to /chat; /agents shows the page's own refusal with no row lit |
| 3 | Tomas switches to Platform and back | In Platform only Work with Chat; back in Operations the four sections return |
| 4 | Priya on /work/cases presses the second area chord, then opens /build/agents | Nothing moves and no tabs draw; all four sections stay; Cases is lit in Work, then Agents in Agent Builder |
| 6 | Search for "knowledge"; Ravi searches "activity" | Each page once, grouped Work, Build, Data, Govern; the pick lights Knowledge in Data Gateway; Ravi is offered no Activity |
| 8 | Priya opens /deployments, /prompt-blocks, /sources, /wiki, /connect, /reviews/all | Each lights its row in its section (Channels and Skills in Agent Builder, the apps and knowledge rows in Data Gateway, Reviews in Governance) and draws a trail |
| 12 | Cells held back, then refused | Skeleton rows and no sections; then the "Pages unavailable. Try again" button (an icon while the sidebar is folded), which loads the sections |
| 13 | Priya opens Settings, then Back | The settings sidebar is open, though the app sidebar starts folded; Back returns to the console with the four sections |
| 14 | Old addresses | /logs/tool-calls, /settings/policies and /account each answer one 307; Policies is at /policies and lit in Governance |
| 15 | Trails at 1440 on the longest pages | No crumb is cut; the Policies trail ends in Policies |
| 16 | Second stack with `OPS_FLAGS=area_tabs`: Priya on /work/cases, then at 390 | Four area tabs Work, Agent Builder, Data Gateway, Governance and no section headings; the second chord opens /build/agents with Agent Builder lit and Cases gone from the sidebar; the first chord returns to /work/cases; at 390 one 44 px Area button |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-723-ui.mjs` | passing, `make usecase-test UC=uc-723 LAYER=ui` (2026-11-12, 15 checks) |

## Non-vacuous check

Step 4 presses the second area chord on /work/cases and expects the page and all four sections to stay; with the tabs
on (step 16) the same chord opens /build/agents and drops Cases from the sidebar, so a chord that does nothing, or tabs
that never come back, fail one of the two. Step 1 fails on a console that lists one area at a time (a missing section),
and step 16 fails on a console that ignores `area_tabs` (no Area group).
