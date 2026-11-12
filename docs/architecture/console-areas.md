# Console areas

Status: current design, 2026-11-11. Code cited at commit 81c9883a. This page covers how the console's navigation is
split into four areas (Work, Build, Data, Govern) and how a person's permission cells decide which areas and pages
they are offered. Today one sidebar shows the four groups to everyone; the area switcher and per-page offering are
designed and not built yet. Cells and roles are described in [roles and permissions](roles-and-permissions.md).

## Status by part

| Part | Status | Where |
|---|---|---|
| One nav file listing every page in four groups | Built | `apps/console/src/lib/nav.ts:67-126` (`NAV`); the groups are labelled Work, Agents, Data Hub and Govern |
| A row offered only when the person holds its cell (`needs`) | Built for the rows that carry `needs` (Activity and its children) | `apps/console/src/components/app-sidebar.tsx:152-154`; `NavNeed` in `lib/nav.ts:18` |
| Group folds remembered per browser | Built | `ops.sidebar.groups`, `app-sidebar.tsx:73` |
| Team switcher with ⌘1–⌘9 | Built | `apps/console/src/components/team-switcher.tsx:37` |
| Cell checks in the console | Built | `useCan`, `useCanCheck` in `apps/console/src/hooks/me-queries.ts:115,132` |
| Thread header links to the agent | Built | `apps/console/src/app/chat/_parts/chat-workspace.tsx:324` |
| Every page carrying its cell, and the sidebar listing one area | Not built | |
| Area switcher, ⌘ shortcuts per area, remembered area | Not built | |
| Home after sign-in and Overview cards chosen by cells | Not built | |
| Chat controls offered by cells, links from a tool call to its tool, call and app | Not built | |
| List pages without bulk selection and row menus when the person lacks the area's edit cell | Not built | |
| Redirects from flat routes to their tree pages | Not built | |

## Rules

| Rule | Effect |
|---|---|
| A page belongs to one area | Each `NAV` entry sits in exactly one area |
| A page is offered when the person holds its cell | The cell is the entry's `needs`; nothing else hides or shows a row |
| An area is offered when it holds at least one offered page | An area with no offered page is absent from the switcher and the shortcuts |
| Roles never appear in navigation | Roles are bundles of cells an admin edits on Access › Roles. Editing a role's cells changes the sidebar on the person's next request, through the token's `perm_version` (rule D62) |
| Pages decide what they allow | A page offered on a view cell draws read only (`ReadOnlyNotice`, `BuilderOnly` in `apps/console/src/components/shared/builder-only.tsx`) |

## Areas and the cells that offer each page (not built)

| Area | Job | Page | Route | Offered when the person holds |
|---|---|---|---|---|
| Work (⌘1) | Do today's work: ask, decide, handle cases, keep your sign-ins | Overview | `/` | `cases.view`, `reviews.view` or `workflows.view` |
| | | Cases | `/cases` | `cases.view` |
| | | Human Tasks | `/reviews` | `reviews.view` |
| | | My accounts | `/integrations/my-accounts` | Always: the person's own sign-ins |
| | | New chat, Chats, All chats | `/chat`, `/chat/conversations` | `chat.run`; another person's chat needs `chat.view` |
| Build (⌘2) | Make and change agents and what they run | Agents | `/agents` | `agents.view` |
| | | Workflows (child: Runs) | `/workflows` | `workflows.view` |
| | | Skills | `/skills` | `skills.view` |
| | | Tools | `/tools` | `tools.view` |
| | | Guardrails | `/guardrails` | `guardrails.view` |
| | | Widgets | `/widgets` | `widgets.view` |
| | | Channels | `/channels` | `deployments.view` |
| Data (⌘3) | Connect systems and curate what agents read and call | Apps | `/integrations` | `connections.view` |
| | | Connections | `/tools/connections` | `connections.view` |
| | | Knowledge bases | `/knowledge` | `knowledge.view` |
| | | Files | `/files` | `files.view` |
| | | Document types | `/document-types` | `documents.view` |
| | | Secrets | `/integrations/credentials` | `secrets_egress.view` |
| Govern (⌘4) | Set the rules, see what happened, decide, prove quality | Policies | `/settings/policies` | `settings.view` |
| | | Reviews | `/reviews/all` | `reviews.decide` or `reviews.manage` |
| | | Activity (children: Tool calls, Background) | `/activity` | `tools.view` or `audit.view`; Background needs `access.manage` in every team |
| | | Audit log | `/logs/audit` | `audit.view` |
| | | Assurance (child: Model inventory) | `/assurance` | `agents.decide` |
| | | Access (children: Roles, Teams, Tool access) | `/access` | `access.view`; changing them needs `access.manage` |
| | | Settings | `/settings` | `settings.view` or `access.manage` |

My account, My security and My memory sit in the user menu at the foot of the sidebar, because they concern the
person rather than an area.

## The area switcher (not built)

| Aspect | Behaviour |
|---|---|
| Control | A dropdown built like the team switcher: `SidebarMenuButton size="lg"` in a `DropdownMenu`, with `DropdownMenuShortcut` per entry. It shows the area's icon, name and page count; folded to icons, the icon only |
| What the sidebar lists | Only the current area's pages, under no heading, plus the Chats group on Work: four to eight rows |
| When it shows | When the person's cells open pages in two or more areas. With one area there is no switcher and the rows show alone |
| Current area | The page shown decides: opening a page from ⌘K, a link or a bookmark switches to that page's area. With no page to go by (sign-in, New chat), the last area the person used, kept per person in the browser under `ops.sidebar.concern`; a person with none lands on Work |
| Keyboard | ⌘1 to ⌘4 pick Work, Build, Data, Govern, skipping areas with no offered page. ⌘K lists every offered page, grouped by area. ⌘B folds the sidebar |
| Home after sign-in | `/chat` when the person holds `chat.run` and no page in Build, Data or Govern; otherwise `/`, whose cards draw by cell: Human Tasks on `reviews.view`, Runs on `workflows.view`, Cases on `cases.view`, Access requests on `access.manage` |
| Phone | The sidebar is a sheet; the switcher sits at its top under the team switcher; the sheet closes when a page is picked |
| Read-only lists | A list page hides bulk selection and row menus when the person lacks the area's edit cell |

### Sequence: opening a page from search (not built)

```
⌘K → person types "knowledge" → list shows offered pages grouped by area
  → person picks Knowledge bases (/knowledge)
  → router navigates; nav.ts maps /knowledge to Data
  → sidebar switches to Data and stores ops.sidebar.concern = data for this person
```

## Chat controls and links back (not built)

| In a chat | Offered when the person holds | Otherwise |
|---|---|---|
| "Add knowledge" chip in the thread header | `knowledge.view` | Hidden |
| Agent chip as a link to `/agents/{id}` | `agents.view` | Plain text |
| Details switch in the thread menu (raw parameters and results) | `agents.edit` | Absent |
| "Save as a workflow" after a repeated plan | `workflows.edit` | Absent |
| Raise on the budget card | `chat.manage` | Continue only |
| Start a workflow among the chat home's starts | `workflows.run` | Absent |
| Open tool, Open call, Open app on an open step | `tools.view`, `tools.view`, `connections.view` | Each link absent on its own |
| Test in the agent | `agents.edit` | Absent |

| From | To | Route | Status |
|---|---|---|---|
| Thread header agent chip | The agent's page | `/agents/{id}` | Built (`chat-workspace.tsx:324`) |
| An open step | The tool's page | `/tools/{id}` | Page built; link not built |
| An open step | The call's row in Activity › Tool calls | `/tools/calls?call={callId}` | List built; filter not built |
| A widget footer's app name | The app's page | `/integrations/{app}` | Page built; link not built |
| A citation's "How it was found" | The knowledge base playground | `/knowledge/{id}?tab=playground` | Built |
| A workflow run card | The run | `/workflows/runs/{id}` | Built |
| Thread menu, Test in the agent | The agent's test panel seeded with the thread's last ask | `/agents/{id}?tab=test&from={threadId}` | Panel built; `from` seed not built |

## Redirects (not built)

`/logs/tool-calls`, the flat `/settings/*` pages and `/account*` answer 307 to their tree pages, once each.

## Components

| Region | Component |
|---|---|
| Team switcher | `TeamSwitcher`, `apps/console/src/components/team-switcher.tsx` |
| Area switcher | A new component on the same `DropdownMenu` and `SidebarMenuButton` parts |
| Rows | `SidebarMenu`, `SidebarMenuItem`, `SidebarMenuButton` (`components/ui/sidebar.tsx`), filtered by `useCanCheck` |
| Chats group | `SidebarChats`, `components/shell/sidebar-chats`, on Work only |
| Header | `SiteHeader`, `components/site-header.tsx`: trigger, breadcrumb trail, search (⌘K), What's new, notifications |
