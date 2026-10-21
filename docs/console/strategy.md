# Console strategy

Status: current, written 2026-10-10 from a read of `apps/console/src` and `docs/architecture/`; every verdict is a
proposal until it is confirmed.

## The strategy

The console renders what the API returns and nothing else. Today it is a mock-backed product of 56 routes, 54 dialog
components, 13 sheet components and 7 multi-step wizards, of which three areas (chat, Cases runs, Reviews) reach a
running service. The work for now is the agentic core: agents, workflows, deployments, chat, Cases and Reviews on the
real agents-service, each proved by a use case at the ui layer. Every other area stays exactly as it is, behind the
mock, and gets no new UI until its service exists. Concretely, "thin UI over the API" in this codebase means that
the hand-written `src/lib/api/*-http.ts` clients (25 files) are replaced area by area by a TypeScript SDK generated
from the services' OpenAPI document; hooks call the SDK; pages render the SDK's response types without joining,
counting or deciding; and `src/lib/api/mock/` becomes a stub that satisfies the same generated types, so a mock can
never describe a field the API lacks.

## Rules

| # | Rule |
|---|---|
| 1 | A page shows only fields a real or designed API call returns. A screen that needs a field no call returns waits for the call; the mock never adds it first. |
| 2 | The console calls the API through one generated SDK. New areas start on the SDK; hand-written `*-http.ts` files are not extended, only replaced. |
| 3 | No new page, tab, dialog or wizard step is built for an area whose service is a stub (platform, hitl, models, kb, files). Fixes to existing mock screens are allowed; additions are not. |
| 4 | Creating anything is one screen: a name and the one required field, then the record page. A wizard is allowed only as a second button and only once the record page exists over a real API. |
| 5 | A page counts as done when its use case passes at the ui layer against the scripted agents-service (`make usecase-test UC=<id> LAYER=ui`). A page with no use case is unproven, whatever it looks like. |
| 6 | One API per capability. A second surface that restates another (a facade, an alias route, a wrapper) is allowed only while a client has not yet absorbed the real contract. It carries its removal task from the day it is written and is deleted in the same commit that moves the client. `/chat/*` is the one open case: it goes when the chat page speaks threads, runs, events and decide through the SDK, with uc-001, uc-002 and uc-009 unchanged as the gate. |

## What exists today

| Fact | Evidence |
|---|---|
| Routes | 56 `page.tsx`: 9 auth, 5 redirects (`/sources`, `/sources/[id]`, `/connect`, `/prompt-blocks`, `/prompt-blocks/[id]`), 42 app pages, 10,396 lines |
| Dialogs and sheets | 54 exported dialog or wizard components, 13 sheet components; 86 `DialogShell` uses, 49 confirm or bulk dialogs, 19 `DetailSheet` uses |
| Wizards | 7 `Stepper` dialogs: prompt generator 7 steps, add source 6, template wizard 6, connect a system 5, generate skill 5, new deployment 3, add tool module 2 |
| Areas on a real service | Chat (`/chat/*`), Cases runs (`/runs`), Reviews (`/reviews`), switched per area in `src/lib/api/index.ts` |
| Areas mock only | Overview, agents, templates, workflows, deployments, skills, wiki, knowledge, connections, sources, tools, files, activity, access, assurance, model inventory, settings, account, sign-in |
| API calls | 54 designed: 4 in code, 17 partial, 33 proposed (`docs/architecture/api.md`) |
| Services | agents-service and tools-service run; the other five are stubs (`docs/architecture/service-map.md`) |
| Use cases with a ui layer | uc-002 (chat approval with step-up) and uc-008 (paused workflow decided from Reviews, seen in Cases) |
| SDK | None. `packages/contracts` is hand-written Python; `sdk-ts` is planned |

## Audit

API column: real (the console calls a running service), partial (a service route exists but the console does not use
it or the shape differs), mock only (a contract and fixture, no service), none designed (no call in `api.md` or any
spec covers it).

| Surface | What it does | API today | Complexity | Verdict | Cut | Proved by |
|---|---|---|---|---|---|---|
| `/chat`, `/chat/[threadId]` | Chat with an agent, stream, citations, tool cards, widgets | Real, on `/chat/*` | 8 components, 1,150 lines | Keep thin | Move onto thread calls later (see Chat) | uc-001 api, uc-002 ui |
| `/chat/conversations` | Workspace-wide chat search and bulk pin, archive, delete | Real list, bulk on `/chat/*` | 299 lines | Defer behind mock | Freeze; the chat rail already lists threads | None |
| `/cases` + run sheet | Runs across workflows, SLA, assign | Real (`/runs`) | 198 lines, 4 views | Keep thin | Drop the email-case fields until a mailbox case exists in the API | uc-008 ui |
| `/cases/[id]` | Email case record: fields, actions, decisions | Mock only | 285 lines | Defer behind mock | Route only RUN-* through `/runs`; CASE-* waits for hitl-service | None |
| `/reviews` + review sheet | Decide paused actions and publish requests | Real (`/reviews`) | 374 lines, 6 components | Keep thin | Hide publish-request rows until agent or workflow publish opens a review | uc-008 ui |
| Bulk decision dialog | Decide many reviews | Partial (`/reviews/bulk-decision`) | 116 lines | Keep thin | None | None; add to uc-008 |
| `/settings/policies/gates` + gate dialog | Conditions that pause a run | Proposed (`GET /v1/review-policies`, read only) | 247 + 184 lines | Defer behind mock | Read only: policies are pinned in the definition, so edits belong in the workflow | None |
| `/` Overview | What needs a decision, agent performance today | None designed | 183 lines | Simplify | Show the Reviews count and the Cases "Needs a person" view; drop performance tiles until metering exists | None |
| `/agents` + templates tab | Find agents, availability, template catalog | Mock only (`/chat/agents` lists seeds) | 364 lines | Simplify | List and New agent only; templates tab off | Needed: agent create |
| New agent dialog | Name, role, model, draft | Proposed (`POST /v1/agents`) | One screen | Keep thin | None | Needed |
| Template wizard | Choose, Configure, Skills, Instructions, Guardrails, Review | None designed | 6 steps | Remove | Duplicates the record page; templates have no API | None |
| `/agents/[id]` | Identity, instructions, tools, knowledge, guardrails, versions, publish, deploy | Proposed (`/v1/agents/{id}`, publish, versions) | 493 lines, 10 dialogs and sheets | Simplify | Keep instructions, tools, Save version, Request publish, Test sheet, Deploy; defer skills, collections, save as template, history | Needed |
| Generate instructions | Prompt generator | None designed | 7 steps, 545 lines | Remove | A text area with one "Draft with AI" call when a model endpoint exists | None |
| `/workflows` | List workflows | Partial (`GET /v1/graphs/{name}/versions`) | 244 lines | Keep thin | None | Needed |
| `/workflows/[id]` | Canvas, Runs, Tests, Deployments, Versions, Settings | Partial (publish without review, versions, runs) | 285-line page, 15 components, 2,504 lines, 28-node palette | Simplify | Canvas shows only node kinds the runtime compiles; Tests and Import CSV wait for the eval API | uc-003, uc-004 api; ui needed |
| Request publish dialog | Changes, checks, tests vs live | Partial (publish has no review step) | 206 lines | Keep thin | Drop "tests vs live" until evals run in a service | Needed |
| `/deployments` + MCP tab | Where each workflow is reachable; MCP endpoint, clients, stats, exposure | Partial (`POST`, `PATCH` paused); MCP none designed | 109-line page, 10 components, 1,609 lines | Simplify | Table of deployments with pause and resume; MCP tab's stat cards, chart, client tiles and settings form deferred | Needed |
| New deployment wizard | Channel, Configure, Review | Partial | 3 steps, 403 lines | Simplify | One screen: workflow, channel, environment | Needed |
| Deployment sheet | Connect, version, rotate key | Partial | 275 lines | Defer behind mock | Version and pause only | None |
| `/skills`, `/skills/[id]` + generate | Skills catalog, record, tests, versions | None designed in `api.md` | 398 + 305 lines, generate 5 steps, 849 lines | Defer behind mock | Remove Generate skill until a skills call exists | None |
| `/wiki`, collections, `/files`, `/knowledge/changes` | Content agents read, provenance, retention | Mock only (kb, files stubs) | 149 + 63 + 294 + 15 lines | Defer behind mock | None now | None |
| `/knowledge`, `/knowledge/[id]` | Knowledge bases, six tabs | Mock only; chat retrieval is a keyword store | 358 + 175 lines | Defer behind mock | None now | None |
| Add source wizard | Type, Scope, Ingestion, Rules, Schedule, Review | Mock only | 6 steps, 927 lines | Remove | The one-screen Add source already exists; the wizard is its duplicate | None |
| `/integrations`, `[id]`, `sources/[id]` | Connections, setup, knowledge sync | Mock only | 354 + 333 + 323 lines | Defer behind mock | None now | None |
| Connect a system wizard | Sign-in, Scopes, Credential, Owner, Review | Mock only | 5 steps, 479 lines | Remove | The draft connection's Setup tab already holds these steps | None |
| `/tools`, `/tools/[id]` | Tool modules, operations, test console, access, approval, credentials | Partial (tools-service has `/v1/calls` only) | 364 + 651 lines, 7 tabs | Defer behind mock | `/tools/[id]` is the largest page and has no module API | uc-007 api (calls only) |
| `/logs/tool-calls`, `/logs/audit` | Tool call log, audit log | Partial (tools-service writes a call log, no read route) | 198 + 240 lines | Defer behind mock | Add one read route before more UI | None |
| `/assurance`, `/model-risk`, `[id]` | Suites, runs, gates, evidence, judges; model inventory | None in code | 212 + 251 + 402 lines, 5 tabs | Defer behind mock | Underthought: stat cards aggregate four sources no single call returns | None |
| `/access` + role, grant dialogs | Roles and grants | Mock only (platform stub) | 116 lines | Defer behind mock | None | None |
| `/settings/*` (7 pages) | Members, API keys, webhooks, notifications, usage, sign-in, storage | Mock only (platform stub; webhooks proposed) | 20 to 418 lines; storage 418 | Defer behind mock | Storage and notifications have no user story in the core; freeze | None |
| Auth pages (9) and `/account/*` | Sign-in, SSO, MFA, invite, profile, sessions | Mock adapter seam | 28 to 178 lines | Keep thin | None; the AuthProvider seam is the right shape | None |
| Small confirms | Delete, revoke, deprecate, legal hold, restore | Follow their area | 49 uses of shared confirm dialogs | Keep thin | None | Their area's use case |

Overbuilt, by size over missing API: the prompt generator (7 steps), add source (6), template wizard (6), connect a
system (5), generate skill (5, 849 lines), `/tools/[id]` (651 lines, 7 tabs), the MCP tab, and the 28-node canvas
palette against a runtime that compiles three graphs. Underthought: Overview (no call designed),
`/chat/conversations` (duplicates the chat rail), `/settings/policies/gates` editing (policies are pinned in definitions),
Assurance stat cards (need a join across eval runs, gates and bundles), and `/cases/[id]` email cases (no case API).

## The agentic core slice

| Step | Surface | Calls that exist | Calls still needed |
|---|---|---|---|
| 1 | Chat with an agent | `/chat/*` 11 routes; `POST /v1/threads`, `runs/stream`, `state` | Chat on the thread calls (later, see Chat) |
| 2 | Create and edit an agent | `GET /chat/agents` (seed list) | `GET`, `POST /v1/agents`, `GET`, `PATCH /v1/agents/{id}`, `POST …/test` |
| 3 | Publish an agent or workflow | `POST /v1/graphs/{name}/versions` (no review) | `POST /v1/agents/{id}/publish` and `/v1/workflows/{id}/publish` opening a review |
| 4 | Start a workflow | `POST /v1/threads`, `POST …/runs/stream` | `GET /v1/workflows`, a "Run now" button calling those two |
| 5 | See it in Cases | `GET /runs`, `GET /runs/{threadId}`, `POST /runs/assign` | None for runs |
| 6 | Decide it in Reviews | `GET /reviews`, `POST /reviews/{threadId}/decision`, `/reviews/assign`, `/reviews/bulk-decision` | Rename to `POST /v1/reviews/{id}/decide`; refuse resume on `runs` (409) |
| 7 | Deploy to a channel | `POST /v1/deployments`, `PATCH` paused | `GET /v1/deployments`, pointer and environment on the row, pause and resume routes |

Order to make them real:

| Order | Work | Why this order |
|---|---|---|
| 1 | Keep uc-002 and uc-008 green; add a ui script to uc-003 that starts a workflow from the console and sees it in Cases | Proves Cases and Reviews already hold with a start button |
| 2 | Publish the agents-service OpenAPI document and generate `sdk-ts`; move cases, reviews and chat clients onto it | Every later area starts on the SDK; the three real areas are the smallest move |
| 3 | Agents calls (list, create, read, edit, test) and the simplified `/agents`, `/agents/[id]` | A workflow pins an agent, so agents come first |
| 4 | Publish through a review for agents and workflows; publish rows in Reviews | Joins steps 3 and 6 on the existing decide path |
| 5 | Deployments list, pause, resume; one-screen New deployment | The last step of the loop |
| 6 | Chat on the thread calls | Only after the above; see the next section |

## Chat

Chat follows the onion in the console: page → `useChatThreads` and `useSendMessage` hooks → `ChatApi` contract →
`chat-http.ts` → agents-service. It does not follow it in the service. `/chat/*` routes call the agent kernel directly
through `turns.drive`, keep their own thread and message tables, and decide approvals through a widget action with a
dev approval token. The design says a chat turn is the `agent_wrapper` graph run on a thread through the same calls as
a workflow, with approvals decided only through Reviews. Today there are two thread models and two approval paths.

| What changes for the page | Today | On the thread calls |
|---|---|---|
| Thread list and create | `GET`, `POST /chat/threads` | `GET`, `POST /v1/threads` with `graph=agent_wrapper`; title, pin and archive need `PATCH /v1/threads/{id}` |
| Sending a message | `POST /chat/threads/{id}/messages` | `POST /v1/threads/{id}/runs/stream` |
| Stream events | `start`, `status`, `tool_start`, `tool_end`, `widget`, `text`, `citations`, `done`, `error` | `run_start`, `node_start`, `node_end`, `interrupt`, `end`, `error`, plus custom node events; the designed set (`text`, `tool_call`, `citation`, `widget`, `waiting_review`, `finished`) is not in code |
| Approval widget | Widget action on `/chat/*`, dev token | `POST /v1/reviews/{id}/decide` with step-up; the widget shows the review |
| Feedback | `PUT /chat/…/feedback` | Proposed on `/v1/threads` |

Recommendation: not now. The page works and uc-001 and uc-002 prove it. The move is worth doing once the designed
event types exist in code, because the console would otherwise translate engine events into chat events, which is a
business rule in the client. Do it as one change in the service (emit the designed events from `agent_wrapper`), then
point `chat-http.ts`, by then the SDK, at the thread calls with uc-002 as the gate.

## Stop doing

| Stop | Until |
|---|---|
| New tabs, wizard steps or stat cards on Assurance, Model inventory, Tools, Skills, Wiki, Knowledge, Connections, Files, Settings | That area's service exists and its first call is in code |
| Adding fields to the mock that no call in `api.md` returns | The call is designed in `api.md` |
| Extending hand-written `*-http.ts` clients | Never; replace with the generated SDK |
| Building wizards as the only way to create | Never; rule 4 |
| MCP tab polish (client tiles, charts, settings form) | MCP deployments exist in agents-service |
| Overview tiles computed from several areas | One overview call is designed and returns them |
| Adding raw palette classes (`text-amber-*`, `bg-emerald-*`, `text-red-*`) or fixed `w-[Npx]` layout widths | Never; 31 files carry 195 today. `check-standards` rule 14 refuses a file that adds one (baseline `apps/console/scripts/palette-baseline.json`), and a lane moves them onto the `success`, `warning` and `destructive` tokens in agentic-core order |

## Open questions

| Question | Default if no answer |
|---|---|
| Remove the four duplicate wizards (prompt generator, template, add source, connect) or hide them behind a flag | Remove; the one-screen dialogs and record pages cover the same fields |
| Generate the SDK from FastAPI's OpenAPI now, or wait for platform-service as the front door | Generate from agents-service now; the console points at platform-service later with the same SDK |
| Hide mock-only nav items in a "real API" build | Show them with a "Preview" label when `NEXT_PUBLIC_OPS_API_URL` is unset for that area |
| Move chat onto the thread calls this week | No; after the designed event types exist |
| Keep `/chat/conversations` | Fold its search into the chat rail and remove the page |
| Canvas palette: 28 node kinds or only those the runtime compiles | Only compiled kinds; the rest return with the interpreter |
