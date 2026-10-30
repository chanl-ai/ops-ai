# A person works from one chat, with every other page in one collapsible sidebar

Status: current. Id: `uc-552`. Service: `console` with `agents-service`. Layers: api, ui. Card: an earlier change.

A person signs in and lands on Chat: a greeting, the composer and up to three hints from their own work. One sidebar
holds New chat, Overview, Cases and Human Tasks (with the count of tasks waiting for them) at the top, their
chats grouped by day, then the console's other pages in groups that fold. Overview lists what is waiting from one
request. When the session ends, a sign-in dialog keeps the page and the unsent draft.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in and a worker | `withUiStack(..., { platform: true, demo: true })`, `stack.startWorker` |
| James and Maya (approver), password `northfield-demo` | The platform seed |
| A Human Task assigned to Maya and a case past its deadline | James starts a refund workflow that waits on a person; Maya assigns its task to herself; James opens a case and moves its deadline into the past |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Maya signs in | She lands on /chat with hints from her work (her task, the late case) and no general starts |
| 2 | She looks at the sidebar | New chat, Overview, Cases and Human Tasks at the top with no heading and no Search row; the one count, on Human Tasks, equals Assigned to me and Overview has none; Chats open, Agents, Data Hub and Govern folded |
| 2c | She looks at the header on Chat | The trail names no Work group, and the agent picker shows the agent's name without the Default mark |
| 3 | She presses her task's hint | A chat starts and shows under Today in the sidebar, marked as the open one |
| 3d | She opens Chat for one agent (`/chat?agent=`) and sends before the agent list has loaded | Send waits for the list; the chat starts on the agent she opened, not the team's default |
| 4 | She opens Overview, searches and opens a task | Four widgets with counts, read from `/v1/overview` only; the search narrows to the case; the task row opens Human Tasks on that task |
| 5 | She opens Agents, folds the sidebar and reloads | The sidebar is still folded and Agents still open |
| 6 | She types a draft, then her session ends | A sign-in dialog over /chat; after signing in again she is back on /chat with the draft |
| 7 | She signs out and in again | The draft is gone |
| 8 | At 375 px she opens the sidebar | It opens as a sheet with her chats, and the page does not scroll sideways |
| 9 | Throughout | No page error |

The non-vacuous checks are step 2 (the count is compared with the Human Tasks list, not with itself) and step 6 (the
session is cleared from another tab, as a refused refresh clears it, and the page must stay).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-552-api.py` | passing |
| ui | `console/scripts/test-uc-552-ui.mjs` | passing |
