# 09 Governance and administration

Status: draft for review.

Builds on ADR-0005 (identity) and ADR-0006 (audit) in `../architecture/decisions/`,
`03-data-and-ai-gateways.md` (call log, approvals), `02-knowledge.md` (curation). The mock is
the reference for UI and API shape: `apps/console/src/lib/types/{team,governance,settings,notifications,search,run-as,knowledge-changes}.ts`,
the matching `apps/console/src/lib/api/*-contract.ts`, `apps/console/src/lib/api/team-context.ts`, and the routes `/logs/tool-calls`,
`/logs/audit`, `/access`, `/settings/*`, `/knowledge/changes`.

## 1. Summary

The console is used by many bank teams at once. A team switcher sets the current team, which travels
on every request as `X-Team-Id` and scopes every list, count and search to the records that team
owns; the Platform team sees all teams. Each team manages its members and roles, where its
notifications go (in the console, email, Microsoft Teams, Slack and any channel the API lists, with
approvals actionable from the channel), its webhooks, its API keys, and reads its usage and model cost
per workflow. Two logs answer "what happened": the tool-call log (every data and AI gateway call,
allowed or denied) and the audit log (every change a person or workflow identity made). `/access`
shows each workflow identity and what it may reach, and who may author, approve and publish. A ⌘K
palette searches records server-side within the team. Knowledge change review sits at
`/knowledge/changes`. Run-as lets a tester act as a staff member or role so tests see what that
person would see.

## 2. Scope

| In | Phase |
|---|---|
| Teams, team switcher, `X-Team-Id` scoping, Platform scope | 1 |
| Members and roles per team (invite, change role, remove) | 1 |
| Audit log with views and filters | 1 |
| Tool-call log over both gateways, with detail | 1 |
| Access: workflow identities, grants (read, extend, revoke), role assignments | 1 |
| Notification feed (bell) and per-team routing to in-console and email | 1 |
| Approve and reject from Microsoft Teams | 1 (if the bank's Teams tenant allows the app, Q3), else 2 |
| Approve and reject from email | Later (needs signed one-time links, Q4) |
| Slack and further channels | Later; modelled as a list from the API, so adding one needs no UI change |
| Run-as principals for playground, agent test, eval cases and the module test console | 1 |
| Knowledge change review at `/knowledge/changes` (source-sync and curation origins) | 1 |
| Knowledge changes proposed by agents (`agent_fix`) | Later (`02` 5.11.7) |
| ⌘K search over workflows, agents, cases, knowledge, chats; recent items | 1 (chats with `07`) |
| Webhooks with delivery history and resend | Later |
| API keys | Later (phase 1 has no external callers) |
| Usage and cost per team and workflow | 1 (reads `03` M7) |
| Create teams in the console | Later (phase 1 teams come from the IdP mapping) |

## 3. Traceability

| Problem statement item | How this spec serves it | Section |
|---|---|---|
| Reason 6: each agent gets its own servers, secrets, keys and logging | One tool-call log over both gateways for every workflow, joined to workflow, run, case and approval | 4.4 |
| Governance: every change recorded | Audit log, append-only, hash-chained (ADR-0006) | 4.3 |
| Decision 1: scoped access with expiry | Grants per workflow identity with expiry, extend, revoke | 4.5 |
| Component 1: cost per workflow | Usage per team and workflow | 4.9 |
| Reference flow: each operations team configures its own path | Team-scoped members, notifications and approvals channels with no platform ticket | 5.2, 5.5 |
| Knowledge requirement 4: re-test on a changed policy | Approving a knowledge change queues the citing workflows' tests | 5.8 |

## 4. Domain model

### 4.1 Teams

| Field | Notes |
|---|---|
| `id`, `name`, `icon` | |
| `ownerGroups[]` | Owner values set on agents, workflows and sources that this team answers for |
| `scope` (`all`, `owned`) | `all` for Platform only |
| `memberCount` | Computed |

### 4.2 Members and roles

| Entity | Fields | Notes |
|---|---|---|
| `Member` | `id`, `name`, `email`, `role` (`admin`, `builder`, `approver`, `viewer`), `teamId`, `status` (`active`, `invited`), `lastActiveAt`, `invitedAt` | Per team; a person can be in several teams |
| `RoleAssignment` | `id`, `principal`, `principalKind` (`person`, `group`), `members`, `teamId`, `capabilities[]` (`author`, `approve`, `publish`), `addedBy`, `addedAt` | Who may author, approve and publish workflows in a team, shown on `/access` |

| Member role | May |
|---|---|
| `admin` | Manage members, keys, webhooks, notification routing and access for the team |
| `builder` | Edit agents and workflows, request publishes |
| `approver` | Decide reviews and drafted actions |
| `viewer` | Read everything in the team |

The two models overlap (open question 1). Proposal: member role is the team-level default;
capabilities are granted to IdP groups and are what `01`'s maker-checker reads. Model Risk and
Security are platform roles held through IdP groups, not team member roles.

### 4.3 Audit entry

`id`, `at`, `actor{kind: person | workflow, name, detail}`, `action` (`created`, `edited`, `published`,
`approved`, `rejected`, `restored`, `deleted`, `granted`, `revoked`, `connected`, `login`), `target{type,
name, href}` (types: workflow, agent, tool, knowledge_base, source, deployment, gate, review,
access_grant, role, member, api_key, webhook, mailbox, notifications, session, model), `teamId`,
`summary`, `diff[{field, before, after}]`, `reason?`, `requestId`. Views: `all`, `publishes`,
`access` (grants, revocations, roles, members, keys), `deletions`. Stored append-only with a hash
chain and exported to the SIEM (ADR-0006).

### 4.4 Tool-call log

One list over both gateways (`03` 4.5 and the model call log of `03` 4.8), as `ToolCallRow`: `id`,
`at`, `gateway` (`data`, `ai`), workflow, agent, `runId`, `caseId`, `target` (operation or alias),
`system` (module or resolved model), `operation` (`read`, `write`, `money_movement`, `completion`),
`record` (the bound record), `approval{kind: person | policy | none, tokenId, by, at, reviewId,
policyName, policyVersion}`, `status` (`ok`, `error`, `denied`, `awaiting_approval`), `latencyMs`,
`tokens`, `cost`. Detail adds `requestId`, `identity`, `request`, `response`, `redacted[]`, the gate
policy in force, and `error`. Stats: failed, error rate, denied, writes approved by a person, awaiting
approval, p95.

### 4.5 Access

| Entity | Fields |
|---|---|
| `WorkflowIdentity` | `id`, `workflowId`, `principal`, `owner`, `team`, `status` (`active`, `suspended`), `grants`, `expiringSoon`, `moneyMovement`, `lastUsedAt` |
| `AccessGrant` | `id`, `identityId`, `workflowId`, `resourceKind` (`module`, `knowledge_base`), `resource`, `scope` (`read`, `write`, `money_movement`), `grantedBy`, `grantedAt`, `expiresAt`, `status` (`active`, `expiring`, `expired`), `reason` |

A grant on a module is the same record as a module approval in `03` 4.2; `/access` and the module's
Access tab are two views of one approvals table.

### 4.6 Run-as principal

`id`, `kind` (`person`, `role`), `name`, `title`, `team`, `collections[]` or null (all), `clearance`
(highest document sensitivity), `tools[]` or null (all), `entitlements[]` (plain-language lines for the
context bar). A turn run as a principal reports what permissions removed: hidden documents and
collections, blocked tools.

### 4.7 Notifications

| Entity | Fields |
|---|---|
| `NotificationChannel` | `id`, `name`, `connected`, `detail`, `actionable` (approvals can be decided from it). Listed by the API; phase 1 seeds `in_app`, `email`, `teams`, `slack` |
| `NotificationRule` | `event` (`approval_waiting`, `sla_at_risk`, `publish_request`, `mailbox_disconnected`), `label`, `description`, `channelIds[]` |
| `NotificationSettings` | `version`, `updatedAt`, `updatedBy`, `channels[]`, `rules[]`; one per team |
| `OpsNotification` | `id`, `kind` (the four events plus `test_regression`, `knowledge_change`), `title`, `body`, `href`, `createdAt`, `read`, `alsoSentTo[]`, `handledElsewhere?` (for example "Approved in Teams by …") |

### 4.8 Webhooks and API keys

| Entity | Fields |
|---|---|
| `Webhook` | `id`, `name`, `url` (https), `events[]` (`review.decided`, `run.completed`, `run.failed`, `case.closed`, `call.denied`, `access.changed`, `audit.created`, `mailbox.disconnected`), `status` (`active`, `paused`, `failing`), `secretPrefix`, `lastDeliveryAt`, `successRate7d`, `deliveries7d`, `team` |
| `WebhookDelivery` | `id`, `event`, `status` (`success`, `failed`, `pending`, `skipped`), `statusCode`, `attempts`, `durationMs`, `at`, `error`, `payload`, `responseBody` |
| `ApiKey` | `id`, `name`, `prefix`, `scopes[]` (`runs:write`, `runs:read`, `logs:read`, `audit:read`, `usage:read`), `createdBy`, `createdAt`, `lastUsedAt`, `expiresAt`, `team` |

### 4.9 Usage

`UsageReport` for 7 or 30 days: `scope` (`all` for Platform, else `team`), totals (runs, tool calls,
tokens, model cost in CAD, cost trend against the previous period), a daily cost series (by team for
Platform, by workflow otherwise), and rows by team and by workflow (runs, tool calls, tokens, model
cost, cost per run, share).

### 4.10 Knowledge change

`KnowledgeChange` as in `apps/console/src/lib/types/knowledge-changes.ts`: origin (`curation`, `agent_fix`,
`source_sync`), proposer, rationale, document, source, section, knowledge bases, from and to version,
before and after text, trust and freshness, optional conflict with another document, the workflows
that cited the passage in 30 days with their test counts, owner, `canDecide`, status (`pending`,
`approved`, `rejected`), decision fields, and `retest` on approval. Views: `mine`, `open`,
`conflicts`, `resolved`.

## 5. Behaviour

### 5.1 Team scoping

1. Every console request carries `X-Team-Id`. The server checks that the session's user is a member
   of that team (or holds a platform role for Platform); the header selects among the user's teams
   and grants nothing on its own.
2. Lists, counts, facets, stats and search return only records whose owner is in the team's
   `ownerGroups`; Platform sees all.
3. Opening a record owned by another team returns 403 with the owning team's id and name, so the
   console can offer to switch (open question 2).
4. Records created inside a team get the team's first owner group as owner.
5. The current team is per browser tab; switching it refetches every view.

### 5.2 Members

1. Invites take a list of addresses; each must be a bank-domain address not already in the team.
   Results are per address (`BulkResult`). Platform admins may invite into any team.
2. Changing a role or removing a member cannot leave a team without an admin; a member cannot remove
   themselves. Each change is audited with before and after.
3. Phase 1 reads membership from IdP groups (the implementation plan B33); the invite flow is for teams without a group.

### 5.3 Logs

1. The tool-call log is written by the gateways (`03` 5.5.1); the console only reads. Rows are
   scoped by the team that owns the workflow. Detail shows request and response with masked paths;
   write inputs are decrypted only for the roles in `03` 8.1.
2. The audit log records every change in every spec with actor, diff, reason and request id. Nothing
   edits or deletes an entry.

### 5.4 Access

1. Granting needs a known resource. Knowledge bases are granted read only. A grant with
   `money_movement` scope must expire within 180 days and carry the approval reference as reason.
   Every grant has an expiry (`03` 4.2); the mock's "no expiry" option is removed (open question 5).
2. Extend pushes expiry out by a number of days from today; revoke takes a reason and takes effect on
   the next call (`03` 5.2.6).
3. A role assignment needs a principal and at least one capability; one assignment per principal per
   team (409).

### 5.5 Notifications and approval channels

1. Each team routes each event to any connected channels; routing to an unconnected channel returns
   400. Saves carry the version read; a newer saved version returns 409 naming who saved it.
2. Channels are a list from the API. A channel marked `actionable` can carry approve and reject for
   `approval_waiting` items. A decision taken in a channel goes through the same review decision
   operation as the console, under the person's own identity, with the same rules (no self-approval,
   four-eyes, reasons). The other copies of the notification then show `handledElsewhere`.
3. An actionable channel never approves by link alone: Teams uses the bank's Entra sign-in in the
   Teams app; email uses a signed one-time link that opens the review in the console (Q4).
4. The bell shows the current user's notifications for the current team, split into today and
   earlier, with mark read and mark all read.

### 5.6 Webhooks and API keys

1. Webhook URLs must be https; at least one event. Deliveries are signed with the webhook secret;
   only its prefix is shown. Only failed deliveries can be resent, and not while paused.
2. An API key's full value is returned once at creation. Keys have scopes and an optional expiry
   (open question 6); revoking makes later calls return 401. Keys act for one team.

### 5.7 Search and run-as

1. ⌘K sends the query to the server, which returns up to a few hits per group with the total;
   pages and actions are listed by the client. Every hit is limited to the current team and to what
   the user may read. Opening a hit records it in the user's recent list.
2. Run-as is available to builders in the playground, the agent test sheet, eval cases (`04` 5.10.2)
   and the module test console (`03` 5.3a). The server applies the principal's entitlements; it never
   widens the tester's own access to data the tester cannot read (open question 7).

### 5.8 Knowledge change review

1. Only the document's owner can decide (403 otherwise); a reason is required and kept in the
   document's history; a decided change cannot be decided again (409).
2. A change with an unresolved conflict cannot be approved (409) until the owner chooses
   `supersede_other` or `keep_both`.
3. Approval publishes the new item version through the ingestion path of `02` and queues the tests of
   every workflow that cited the passage in the last 30 days (`04` 5.8.6, `02` 5.5.6).
4. Placement: `/knowledge/changes` is one queue across the team's knowledge bases, filterable by
   knowledge base and linked from each knowledge base page and from the `knowledge_change`
   notification. `02`'s curation tasks that propose a text change appear here; tasks with no proposed
   text (held, failed, no answer) stay in `02`'s curation queue.

## 6. API

Paths follow the mock's HTTP clients under `/v1`. All lists take `ListParams` and return
`ListResult` with server-computed facets.

### 6.1 Teams, members, search, run-as

| # | Operation | Request | Response | Errors | Phase |
|---|---|---|---|---|---|
| G1 | `GET /v1/teams` | | `Team[]` the user belongs to | | 1 |
| G2 | `POST /v1/teams` | `name`, `ownerGroup` | `Team` | 409 name taken | Later |
| G3 | `GET /v1/settings/members` | filters `role`, `status`, `teamId` | `ListResult<Member>` | | 1 |
| G4 | `POST /v1/settings/members/invite` | `emails[]`, `role`, `teamId?` | `BulkResult` | | 1 |
| G5 | `POST /v1/settings/members/role` | `ids[]`, `role` | `BulkResult` (last admin skipped) | | 1 |
| G6 | `POST /v1/settings/members/delete` | `ids[]` | `BulkResult` | | 1 |
| G7 | `GET /v1/search?q=` | | `SearchResults` | | 1 |
| G8 | `GET /v1/search/recent`, `POST /v1/search/recent` | hit | `SearchHit[]` / 204 | | 1 |
| G9 | `GET /v1/run-as/principals` | | `RunAsPrincipal[]` | | 1 |
| G10 | `GET /v1/settings/lookups` | | roles, webhook events, API scopes | | 1 |

### 6.2 Logs

| # | Operation | Request | Response | Phase |
|---|---|---|---|---|
| L1 | `GET /v1/logs/tool-calls` | filters `gateway`, `operation`, `approval`, `status`, `workflowId`; text; time range | `ListResult<ToolCallRow> & { stats }` | 1 (same as `03` G3) |
| L2 | `GET /v1/logs/tool-calls/{id}` | | `ToolCallDetail` | 1 (same as `03` G4) |
| L3 | `GET /v1/logs/audit` | `view`, filters `action`, `targetType`, `actorKind`, `teamId`; text; time range | `ListResult<AuditEntry> & { viewCounts }` | 1 |
| L4 | `GET /v1/logs/audit/export` | time range, filters | signed export with chain proof | Later |

### 6.3 Access

| # | Operation | Request | Response | Errors | Phase |
|---|---|---|---|---|---|
| P1 | `GET /v1/access/identities` | | `ListResult<WorkflowIdentity> & { stats }` | | 1 |
| P2 | `GET /v1/access/grants` | `view` (`all`, `expiring`, `expired`), filters | `ListResult<AccessGrant> & { viewCounts }` | | 1 |
| P3 | `POST /v1/access/grants` | `GrantInput` | `AccessGrant` | 400 unknown resource, knowledge base not read, money grant over 180 days or without reason; 409 already granted | 1 (module grants go through `03` approvals, ADR-0005; this creates knowledge base grants) |
| P4 | `POST /v1/access/grants/revoke` | `ids[]`, `reason` | `BulkResult` | | 1 |
| P5 | `POST /v1/access/grants/extend` | `ids[]`, `days` | `BulkResult` | | 1 |
| P6 | `GET /v1/access/roles` | filters | `ListResult<RoleAssignment>` | | 1 |
| P7 | `POST /v1/access/roles` | `RoleInput` | `RoleAssignment` | 400; 409 | 1 |
| P8 | `POST /v1/access/roles/delete` | `ids[]` | `BulkResult` | | 1 |
| P9 | `GET /v1/access/options` | | workflows, modules, knowledge bases, people, groups, teams | | 1 |

### 6.4 Notifications, webhooks, keys, usage, knowledge changes

| # | Operation | Request | Response | Errors | Phase |
|---|---|---|---|---|---|
| N1 | `GET /v1/notifications` | | `NotificationFeed` | | 1 |
| N2 | `POST /v1/notifications/read`, `/read-all` | `ids[]` | `NotificationFeed` | | 1 |
| N3 | `GET /v1/settings/notifications` | | `NotificationSettings` | | 1 |
| N4 | `PUT /v1/settings/notifications` | `version`, `rules[]` | `NotificationSettings` | 400 unconnected channel; 409 newer version | 1 |
| N5 | Channel callbacks (Teams action, email link) | signed action payload | review decision via `01` operation 35 | 401, 403, 409 | 1 (Teams, Q3), later (email) |
| W1 | `GET /v1/settings/webhooks`, `POST`, `DELETE /{id}`, `POST /{id}/status` | `WebhookInput`; `status` | `Webhook` | 400 not https, no events | Later |
| W2 | `GET /v1/settings/webhooks/{id}/deliveries`, `POST .../{deliveryId}/resend` | | `WebhookDelivery` | 409 paused or not failed | Later |
| K1 | `GET /v1/settings/api-keys`, `POST`, `DELETE /{id}` | `ApiKeyInput` | `{key, apiKey}` once; `ApiKey` | 400 no name or scopes | Later |
| U1 | `GET /v1/settings/usage?days=7\|30` | | `UsageReport` | | 1 |
| KC1 | `GET /v1/knowledge-changes` | `view`, `kbId?`, filters `origin`, `kbId`, `owner` | `ListResult<KnowledgeChange> & { viewCounts }` | | 1 |
| KC2 | `GET /v1/knowledge-changes/{id}` | | `KnowledgeChange` | 404 | 1 |
| KC3 | `POST /v1/knowledge-changes/{id}/decision` | `decision`, `reason` | `KnowledgeChange` with `retest` | 400 no reason; 403 not owner; 409 decided or unresolved conflict | 1 |
| KC4 | `POST /v1/knowledge-changes/{id}/conflict` | `resolution` | `KnowledgeChange` | 403; 409 no conflict | 1 |

**Phase-1 count: 31 operations** (G1, G3–G10, L1–L3, P1–P9, N1–N5, U1, KC1–KC4; L1 and L2 are
shared with `03`).

## 7. UI mapping

| Route or element | API | Gaps between mock and spec |
|---|---|---|
| Team switcher in the shell | G1 | Team create (G2) is later |
| ⌘K palette | G7, G8 | None |
| Bell and notification popover | N1, N2 | None |
| `/logs/tool-calls` with detail sheet | L1, L2 | None |
| `/logs/audit` | L3 | Export is later |
| `/access` Identities, Grants, Roles tabs | P1–P9 | Remove the "no expiry" choice in the grant dialog (5.4.1) |
| `/settings/members` | G3–G6, G10 | None |
| `/settings/notifications` | N3, N4 | Slack shown as not connected; connecting a channel is an admin task outside the console in phase 1 |
| `/settings/webhooks`, deliveries sheet | W1, W2 | Phase 1 hides the page or shows it read-only |
| `/settings/api-keys` | K1 | Phase 1 hides the page |
| `/settings/usage` | U1 | None |
| `/knowledge/changes` and the change sheet | KC1–KC4 | None |
| Run-as bar (playground, agent test, eval case dialog, module test console, model validation "Deciding as") | G9 | In the validation form, run-as only previews who may not decide; the server uses the session |

## 8. Security, audit and evidence

| Action | Role |
|---|---|
| Switch to a team | Members of that team; platform roles for Platform |
| Manage members, notification routing, webhooks, API keys | Team `admin` |
| Read logs | Members, scoped to their team; Security and Audit see all |
| Grant, extend, revoke access | Module owner team (modules, `03` 8.1); knowledge owner (knowledge bases); Security may revoke any |
| Assign author, approve, publish capabilities | Team `admin`, audited |
| Decide knowledge changes | The document's owner |
| Read usage | Team members; Platform sees all teams |

Audited: member invited, role changed, member removed, grant created, extended or revoked, role
assignment added or removed, notification settings saved (with version), webhook created, paused,
deleted, delivery resent, API key created or revoked, knowledge change decided or conflict resolved,
team switched (as `session`).

## 9. Non-functional

| Concern | Target (phase 1 assumption) |
|---|---|
| Search | p95 under 300 ms for the first hits per group |
| Logs | Tool-call list p95 under 1 s over 30 days; detail under 500 ms |
| Notification to channel | Under 60 s from the event |
| Teams approval round trip | Decision recorded under 5 s after the click |
| Audit | Written in the same transaction as the change; a change that cannot be audited fails |
| Retention | Audit and tool-call logs per the retention owner (architecture overview open question 4); notifications 90 days |

## 10. Acceptance tests (phase 1)

| # | Test | Fails if |
|---|---|---|
| GV1 | Send `X-Team-Id` of a team the user is not in | Any record is returned |
| GV2 | As Lending Ops, list workflows, search for a Card Services workflow, and open it by URL | It appears in the list or search, or opening it returns anything but 403 naming Card Services |
| GV3 | Remove the last admin of a team | The removal succeeds |
| GV4 | Grant `money_movement` access for 365 days | The grant is created |
| GV5 | Revoke a grant during a run | The next gateway call is allowed |
| GV6 | Route `approval_waiting` to Slack while it is not connected | The save succeeds |
| GV7 | Two admins save notification routing from the same version | The second save succeeds |
| GV8 | Approve a drafted action from Teams as its requester | The approval is recorded |
| GV9 | Approve from Teams | The console's copy does not show `handledElsewhere`, or no audit entry names the person |
| GV10 | A gateway call is denied | No tool-call row with `status: denied` and the deny reason |
| GV11 | Edit an audit row in the database | The chain verification passes |
| GV12 | Approve a knowledge change with an unresolved conflict | The approval succeeds |
| GV13 | Approve a knowledge change cited by a workflow | No tests are queued for that workflow |
| GV14 | Run an agent test as a teller | A restricted document is cited or a blocked tool is called |
| GV15 | Usage as Lending Ops | Any other team's workflow appears |

## 11. Decisions and open questions

### Decisions this spec makes

| Decision | Reason |
|---|---|
| `X-Team-Id` selects among the user's teams and is checked against membership | A header from the browser cannot be authority |
| Grants on `/access` and module approvals are one table | One fact, one home (`03` 4.2) |
| Channel approvals call the same decision operation under the person's identity | Rules for self-approval and four-eyes hold in every channel (design lessons, HITL) |
| Notification channels are a list from the API | Adding Slack or another channel needs configuration and no UI change |

### Open questions

| # | Question | Blocks |
|---|---|---|
| Q1 | One role model or two: team member roles (`admin`, `builder`, `approver`, `viewer`) and author, approve, publish capabilities? Proposal in 4.2 | Maker-checker (`01` 5.5) |
| Q2 | May a 403 name the owning team, given `03` 5.3.10 hides existence from gateway callers? The console audience is staff; the proposal is yes in the console and no at the gateways | 5.1.3 |
| Q3 | Does the bank allow an Ops AI app in its Teams tenant, with actionable messages signed in through Entra? | Teams approvals |
| Q4 | Are approval links by email acceptable to Security, and with what expiry? | Email approvals |
| Q5 | Confirm that every grant expires (the mock allows no expiry outside money movement) | 5.4.1 |
| Q6 | Must API keys expire, and what maximum? | API keys |
| Q7 | Who may run as which principal: any builder as any role, or only roles within the builder's own entitlements? | Run-as |
| Q8 | Which IdP groups map to teams and to the member roles in 4.2, and who maintains the mapping? ADR-0005 defines workflow and platform identities but not console roles per team | Teams in phase 1 |
