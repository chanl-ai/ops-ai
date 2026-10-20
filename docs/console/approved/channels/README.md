# Channels, as approved

Status: current. The maintainers approved these screens on 2026-10-18 ("looks perfect, build it"). The real Channels pages
are built to match them; a difference is a defect unless the maintainers approves a new version here.

Approved build: console at `2214c5a1`, routes under `/preview/channels` on sample data
(`apps/console/src/app/preview/channels`). Card c-242; architecture in `.codeloop/specs/242-*/plan.md`. The walk that
checks them is uc-165 (`docs/usecases/console/channels-preview.md`).

| Screen | Route | 1280 px | 400 px |
|---|---|---|---|
| Hub: a card per kind, then every connection with what it serves, version, status and 24-hour traffic | `/preview/channels` | [hub-1280](hub-1280.png) | [hub-400](hub-400.png) |
| Arriving from the old Deployments address | `/preview/deployments` | [from-deployments-1280](from-deployments-1280.png) | [from-deployments-400](from-deployments-400.png) |
| Email: landing (state, what it includes, 7-day count, View activity) and its mailboxes | `/preview/channels/email` | [email-1280](email-1280.png) | [email-400](email-400.png) |
| Chat embed | `/preview/channels/chat` | [chat-1280](chat-1280.png) | [chat-400](chat-400.png) |
| API | `/preview/channels/api` | [api-1280](api-1280.png) | [api-400](api-400.png) |
| A kind coming soon (MCP; Slack and Teams the same) | `/preview/channels/mcp` | [mcp-1280](mcp-1280.png) | [mcp-400](mcp-400.png) |
| An agent's Channels tab: versions live, and where it answers with version, status and traffic | `/preview/channels/agent` | [agent-1280](agent-1280.png) | [agent-400](agent-400.png) |
| Activity, opened from a channel's View activity | `/preview/channels/activity?channel=email` | [activity-1280](activity-1280.png) | [activity-400](activity-400.png) |

What the real pages must keep:

| Part | Rule |
|---|---|
| Layout | Full width inside `PageLayout`, actions in the header, a tab per channel kind with a health dot |
| Status words | Active, Needs attention, Not set up, Coming soon; never a bare count |
| Serves | Changed in the row: the workflow or agent, then Latest or a pinned version that says how far behind it is |
| Connections list | The shared data table with select and id columns, search and filters |
| Activity | A count and View activity on a channel, agent or workflow page; the rows live only on the Activity page |

Known differences the maintainers accepted, and the card that removes each:

| Difference from the screens | Why | Removed by |
|---|---|---|
| An API key row serves "Any of <team>'s workflows", with no picker and no traffic | A key is not bound to one agent or workflow and leaves no stable mark on a run | c-246 (a key gets one target and its runs are counted) |
| An email row always runs Latest, with no pin choice; when several workflows watch the address the row names the live one "and N more" | A workflow's trigger names the mailbox and runs the live version; nothing can pin it | None planned; accepted |
