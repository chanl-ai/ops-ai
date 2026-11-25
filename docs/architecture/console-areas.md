# Console areas

Status: current, updated 2026-11-18 from `apps/console/src/lib/nav.ts`. The chat controls and links back further down
are the 2026-11-11 design and were not rechecked.

The console's pages fall into four areas: Work, Agent Builder, Data Gateway and Governance. A person is offered only
the pages their permission cells open, and an area with no such page is left out. Cells and roles are described in
[roles and permissions](roles-and-permissions.md).

## Status by part

| Part | Status | Where |
|---|---|---|
| One nav file listing every page in four areas | built | `NAV` in `apps/console/src/lib/nav.ts`; on screen the areas are Work, Agent Builder, Data Gateway and Governance (`AREA_LABEL`) |
| Every row carries the cell that offers it; a section with no offered row is left out | built | `itemOffered`, `rowsOfArea` and `sidebarSections` in `apps/console/src/lib/nav.ts` |
| One sidebar with every area as a section, one link per page, child pages as tabs on the page | built | `sidebarSections`; `SectionTabs` |
| Area switcher with ⌘1 to ⌘4 and the last area and page remembered per person in the browser | built behind the `area_tabs` flag | `apps/console/src/components/shared/area-switcher.tsx` (key `ops.sidebar.area`) |
| Team switcher with ⌘1–⌘9 | built | `apps/console/src/components/team-switcher.tsx` |
| Cell checks in pages | built | `useCan`, `useCanCheck` in `apps/console/src/hooks/me-queries.ts` |
| Old flat routes (the ones in `MOVED`, such as agents, cases and tools) answer one 307 to their page, query kept | built | `proxy.ts`, `MOVED` in `apps/console/src/lib/routes/moved.ts` |
| Chat controls offered by cells, links from a tool call to its tool, call and app | partial | Below |

## Rules

| Rule | Effect |
|---|---|
| A page belongs to one area | Each `NAV` entry sits in exactly one area |
| A page is offered when the person holds its cell | The cell is the entry's `needs` (or one of `or`); nothing else hides or shows a row |
| An area is offered when it holds at least one offered page | An area with no offered page is absent from the sidebar, the switcher and the shortcuts |
| Roles never appear in navigation | Roles are bundles of cells an admin edits on Governance › Access › Roles. Editing a role's cells changes the sidebar on the person's next request, through the token's `perm_version` (rule D62) |
| Pages decide what they allow | A page offered on a view cell draws read only (`ReadOnlyNotice`, `BuilderOnly` in `apps/console/src/components/shared/builder-only.tsx`) |

## Areas and the cells that offer each page

| Area | Job | Page | Route | Offered when the person holds |
|---|---|---|---|---|
| Work | Do today's work: ask, decide, handle cases | Overview | `/overview` | `cases.view`, `reviews.view` or `workflows.view` |
| | | Cases | `/work/cases` | `cases.view` |
| | | Human Tasks | `/work/tasks` | `reviews.view` |
| | | Chat (child: All chats) | `/chat` | `chat.run` |
| | | My apps (user menu) | `/work/apps` | Always: the person's own sign-ins |
| Agent Builder | Make and change agents and what they run | Agents | `/build/agents` | `agents.view` |
| | | Workflows (child: Runs) | `/build/workflows` | `workflows.view` |
| | | Channels | `/build/channels` | `deployments.view` |
| | | Skills | `/build/skills` | `skills.view` |
| | | Guardrails | `/build/guardrails` | `guardrails.view` |
| | | Widgets | `/build/widgets` | `widgets.view` |
| Data Gateway | Connect systems and curate what agents read and call | Knowledge bases | `/data/knowledge` | `knowledge.view` |
| | | Apps | `/data/connectors` | `connections.view` |
| | | Tools | `/data/tools` | `tools.view` |
| | | Secrets | `/data/secrets` | `secrets_egress.view` |
| | | Files | `/data/files` | `files.view` |
| | | Document types | `/data/document-types` | `documents.view` |
| Governance | Set the rules, see what happened, decide, prove quality | Activity (children: Tool calls, Audit log) | `/govern/activity` | The activity cells; each child its own |
| | | Reviews | `/govern/reviews` | `reviews.view` |
| | | Access (children: Roles, Tool access) | `/govern/access` | `access.view`; changing them needs `access.manage` |
| | | Policies | `/govern/policies` | `settings.view` or `access.manage` |
| | | Evals (child: Model inventory) | `/govern/evals` | `agents.decide` |
| | | Settings | `/settings` | `settings.view` or `access.manage` |

My account, My security and My memory sit in the user menu at the foot of the sidebar, because they concern the
person rather than an area.

## The area switcher (built behind the `area_tabs` flag)

| Aspect | Behaviour |
|---|---|
| Control | A dropdown built like the team switcher: `SidebarMenuButton size="lg"` in a `DropdownMenu`, with `DropdownMenuShortcut` per entry. It shows the area's icon, name and page count; folded to icons, the icon only |
| What the sidebar lists | Only the current area's pages, under no heading, plus the Chats group on Work: four to eight rows |
| When it shows | When the person's cells open pages in two or more areas. With one area there is no switcher and the rows show alone |
| Current area | The page shown decides: opening a page from ⌘K, a link or a bookmark switches to that page's area. With no page to go by (sign-in, New chat), the last area the person used, kept per person in the browser under `ops.sidebar.area`; a person with none lands on Work |
| Keyboard | ⌘1 to ⌘4 pick Work, Build, Data, Govern, skipping areas with no offered page. ⌘K lists every offered page, grouped by area. ⌘B folds the sidebar |
| Home after sign-in | `/chat` when the person holds `chat.run` and no page in Build, Data or Govern; otherwise `/`, whose cards draw by cell: Human Tasks on `reviews.view`, Runs on `workflows.view`, Cases on `cases.view`, Access requests on `access.manage` |
| Phone | The sidebar is a sheet; the switcher sits at its top under the team switcher; the sheet closes when a page is picked |
| Read-only lists | A list page hides bulk selection and row menus when the person lacks the area's edit cell |

### Sequence: opening a page from search

```
⌘K → person types "knowledge" → list shows offered pages grouped by area
  → person picks Knowledge bases (/data/knowledge)
  → router navigates; nav.ts maps /data/knowledge to Data
  → sidebar switches to Data Gateway and stores ops.sidebar.area = data for this person
```

## Chat controls and links back

| In a chat | Offered when the person holds | Otherwise |
|---|---|---|
| "Add knowledge" chip in the thread header | `knowledge.view` | Hidden |
| Agent chip as a link to `/build/agents/{id}` | `agents.view` | Plain text |
| Details switch in the thread menu (raw parameters and results) | `agents.edit` | Absent |
| "Save as a workflow" after a repeated plan | `workflows.edit` | Absent |
| Raise on the budget card | `chat.manage` | Continue only |
| Start a workflow among the chat home's starts | `workflows.run` | Absent |
| Open tool, Open call, Open app on an open step | `tools.view`, `tools.view`, `connections.view` | Each link absent on its own |
| Test in the agent | `agents.edit` | Absent |

| From | To | Route | Status |
|---|---|---|---|
| Thread header agent chip | The agent's page | `/build/agents/{id}` | Built (`chat-workspace.tsx:323`) |
| An open step | The tool's page | `/data/tools/{id}` | Page built; link not built |
| An open step | The call's row in Activity › Tool calls | `/govern/activity/tool-calls?call={callId}` | List built; filter not built |
| A widget footer's app name | The app's page | `/data/connectors/{app}` | Page built; link not built |
| A citation's "How it was found" | The knowledge base playground | `/data/knowledge/{id}?tab=playground` | Built |
| A workflow run card | The run | `/build/runs/{id}` | Built |
| Thread menu, Test in the agent | The agent's test panel seeded with the thread's last ask | `/build/agents/{id}?tab=test&from={threadId}` | Panel built; `from` seed not built |

## Redirects

Old flat routes answer one 307 to their tree page before any page renders: `proxy.ts` looks each path up in `MOVED` (`apps/console/src/lib/routes/moved.ts`, longest prefix first) and keeps the rest of the path and the query. Four more (`/logs/tool-calls`, `/settings/policies`, `/account`, `/account/security`) are in `redirects()` in `apps/console/next.config.ts`. Every route in the tables on this page is checked against the console's pages by `scripts/check-doc-routes.mjs`.

## Components

| Region | Component |
|---|---|
| Team switcher | `TeamSwitcher`, `apps/console/src/components/team-switcher.tsx` |
| Area switcher | `AreaSwitcher`, `apps/console/src/components/shared/area-switcher.tsx`, on the same `DropdownMenu` parts |
| Rows | `SidebarMenu`, `SidebarMenuItem`, `SidebarMenuButton` (`components/ui/sidebar.tsx`), filtered by `useCanCheck` |
| Chats group | `SidebarChats`, `components/shell/sidebar-chats`, on Work only |
| Header | `SiteHeader`, `components/site-header.tsx`: trigger, breadcrumb trail, search (⌘K), What's new, notifications |
