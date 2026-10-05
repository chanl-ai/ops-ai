# Page plan

Status: current.

Ops AI is the operations console for a bank's AI agents: what the agents did, what is waiting on a person, and the configuration behind both. Two areas share one shell. **Agent Studio** covers agents, workflows and human review. **Data Hub** covers knowledge and tools.

## Rules every page follows

| Rule | Source |
| --- | --- |
| Header is `PageLayout` (icon, title, description, actions). Record pages pass `backHref`. | `apps/console/src/components/page-layout.tsx` |
| Lists are `DataTableWithViews` with faceted filters, server pagination and an `EmptyState`. Bulk actions move into the page header. | `apps/console/src/components/data-table-with-views.tsx` |
| First load shows `PageSkeleton`. Errors show `EmptyState` with `AlertCircle` and a "Try again" action. Empty lists show an `EmptyState` with the create action. | `apps/console/src/components/shared/query-states.tsx`, `page-skeleton.tsx`, `empty-state.tsx` |
| Create or edit one entity with ≤ 7 fields: `DialogShell` size `md`. Multi-step create: `DialogShell` + `Stepper`. Inspect a row: `DetailSheet` with prev/next. Delete: `DeleteDialog`. | Dialog rules in `apps/console/CLAUDE.md` |
| Record pages: `RecordLayout` (320px rail of `AttributeCard` + `FieldRow`, tabbed main). | `apps/console/src/components/shared/record-layout.tsx` |
| Components take props only. Pages get data from `hooks/`, hooks call `lib/api`, and fixtures exist only in `lib/api/mock`. | `apps/console/CLAUDE.md` |

## Pages

| Route | Job | Data (hook → API) | Dialogs and sheets |
| --- | --- | --- | --- |
| `/` Overview | Show what needs a decision now and how the agents performed today | `useOverview` → `overview.get` | none; rows link to Reviews |
| `/agents` | Find an agent and see its volume and auto-resolve rate | `useAgents(params)` → `agents.list` | Create agent (`DialogShell` md) |
| `/agents/[id]` | One settings page: identity, instructions, tools, knowledge, guardrails; every Save is a new version; rail shows which workflows use it and the version each is pinned to | `useAgent`, `useAgentVersions`, `useTools` | Save as version (sm), Grant tools (md), Collections (sm), History sheet, Test sheet, Delete |
| `/workflows` | List workflows with their run volume and review rate | `useWorkflows(params)` → `workflows.list` | Create workflow (md) → opens editor |
| `/workflows/[id]` | Tabs: Canvas (28-node palette, inspector, checks), Runs, Tests, Deployments, Versions, Settings | `useWorkflow`, `useWorkflowRuns`, `useTests`, `useDeployments` | Request publish (lg: changes, checks, tests vs live), Add test (md), Import CSV (md), Run sheet, Restore version (sm) |
| `/deployments` | Where each published workflow is reachable: chat widget, API, email | `useDeployments` → `deployments.*` | New deployment wizard (Channel, Configure, Review), Deployment sheet (connect, version, rotate key) |
| `/reviews` | Decide paused agent actions and publish requests, soonest SLA first. Publish requests need a different person to approve | `useReviews(params)` → `reviews.list`, `reviews.decide`, `reviews.assign` | Review `DetailSheet` with decision form and prev/next |
| `/reviews/policies` | Set which conditions pause a run and who reviews | `useGatePolicies` → `policies.*` | Create/edit gate (md), Delete gate |
| `/knowledge` | Manage the sources agents may cite | `useSources(params)` → `sources.*` | Add source wizard (Stepper: type, details, access), Test query sheet, Delete |
| `/tools` | Tool modules (one per system) with type, version, operations, access classes, approval state and expiry, workflows, 24h calls and errors; views Needs approval, Expiring soon, Failing; Catalog tab of known systems. Design: `docs/ui/tools-design.md` | `useToolModules(params)`, `useToolCatalog` → `toolModules.*` | Add module (lg, 3 steps: source, operations, review), Delete, bulk Delete |
| `/tools/[id]` | One module: Operations (sheet: schema, record binding, limits, approval), Test console (run as a workflow's case, stub or test environment), Access (workflow approvals with expiry), Approval (security review per major version), Credentials (vault references), Activity (calls chart, recent calls), Versions (view changes). Operation edits stage a version | `useToolModule`, `useModuleActivity`, `useTestModule` | Request approval (md), Reject/Revoke reason (sm), Publish version (md), Request review (sm), Change reference (sm), Delete |
| `/chat`, `/chat/[id]` | Chat with a live agent (`ChatLayout`): rail of chats (pinned, today, 7 days, older; rename, pin, archive, delete, ⌘K new), streamed replies grounded in the chosen knowledge bases with citations, tool-call cards, and MCP App widgets (table, chart, record, metric, approval, form). Approval widgets decide their review in the Reviews queue | `useChatThreads`, `useChatThread`, `useSendMessage` (stream store) → `chat.*`; `useKnowledgeBases` for the picker | Document sheet from a citation, Feedback reason (sm), Reject reason (sm), Delete chat |
| `/chat/conversations` | Find any chat in the workspace by agent, knowledge base, state or owner | `useChatThreads(params)` → `chat.threads.list` | Bulk pin, archive (confirm), delete (confirm); row actions |

## States designed per page

| State | How to see it |
| --- | --- |
| Loading | `?mock=slow` holds every request for 2.5 s |
| Error | `?mock=error` fails every request |
| Empty | `?mock=empty` returns no rows |
| Reply fails part-way | `?chat=fail-next` makes the next chat reply stop half-way with an error and Retry |

## Decisions

| Decision | Choice |
| --- | --- |
| What deploys | Workflows only. An agent is configuration; a chat agent is the workflow Chat message → Agent → Reply |
| Agent version in a workflow | Pinned when the workflow publishes; agent saves reach production on the workflow's next publish |
| Evals before publish | Advisory: results travel with the publish request and never block it |
| Who approves a publish | Another publisher, in the Reviews queue |
| Guardrails | Agent settings, so they apply wherever the agent is used |
| First channels | Chat widget, API, email |
