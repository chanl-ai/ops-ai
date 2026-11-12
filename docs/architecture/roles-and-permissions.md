# Roles and permissions

Status: current, 2026-11-11. This is the one page for who may do what in Ops AI, approvals included ([Approvals](#approvals)). Before asking an access
question, look it up in [Access rules](#access-rules); before writing a refusal, a role check, a lock or a
closed default, look it up in the [Exceptions register](#exceptions-register). Code is cited at commit `c96319da`.
The grid below is generated from `packages/ops_access` and checked by `make python-verify`; the register is checked by
`scripts/check_access_exceptions.py` on every commit: every 403 (typed errors included) and every 409 code against a
line of `access-exceptions-allowlist.txt`, every line's row against this register (a resolved row holds no lines; a
line added on a row with no decision fails, and the lines already on one are printed for review), and every
exception line added since the list began against a `Standards-exception:` trailer on its commit that says
`approved by a maintainer`.

## How access is decided

Every access decision is one call, `ops_access.can(principal, area, action, team=, owner=, not_by=, requested_by=)`
(`packages/ops_access/src/ops_access/check.py:127`). It answers from two sources and nothing else:

| Source | What it holds | Who changes it |
|---|---|---|
| The roles grid | Role × (area, action) cells, scope `all` or `own`; a person holds roles per team through assignments | Admins (`access` cells) |
| Govern › Policies | Stricter rules a workspace or team switches on, each with an open default | Whoever holds the policy's `changed_by` cell |

The rules for both (CLAUDE.md "No hard coding"):

| Rule | Consequence |
|---|---|
| Every permission and approval is a grid cell or a setting | Each one is a cell an admin ticks in the roles grid or a policy an admin changes. A rule that is neither is a defect, or a register row that says why |
| Defaults are open, except the safe approval defaults | A new workspace meets no control until an admin sets one, except the rows listed below. Each is still a setting a team can loosen |
| Admins can do everything | The built-in Admin role holds every cell in its team (migration `0016_admin_every_cell`). The exceptions are rows E02, E26 and E27 |
| A refusal behind neither the grid nor a policy is a defect | Unless the [Exceptions register](#exceptions-register) records a decision for it |
| Definitions are database records | Built-in workflows, roles and task types are seeded and editable through `can()`, never locked in code |
| Security sits in the step that acts | Separation of duties is a step setting (`notDecidedBy`) and a team policy (`requesterMayDecide`), never a lock on a definition |

The safe default for approvals:

| Row | Safe default | Setting that loosens it |
|---|---|---|
| E51 | The person who asked for, saved or started a decision does not take it | `requesterMayDecide`, turned on |

The other defaults that start closed are AI features off (E03, E36), publish review on major changes (E01), chat
threads read only by whoever started them (E02), personal data masked in AI steps (E34) and new addresses asking
Security (E48). Every policy whose `Open?` column says no in [Policies](#policies) cites its row.

### The always-on baseline

These hold whatever the grid and policies say. A 403 with one of these codes needs no register row
(`BASELINE` in `scripts/check_access_exceptions.py`).

| Control | Codes | Where |
|---|---|---|
| Token identity: every caller is a verified token, key or service token; dev headers only in dev | 401, `permissions_changed`, `api_key_refused`, `not_the_invitee`, `key_not_registered` | `packages/ops_identity/src/ops_identity/resolve.py`, `fastapi.py:13` |
| Tenant isolation: another tenant's record is not found | 404, `tenant_required` | store tenant filter and PostgreSQL row-level security (data model) |
| Team isolation: another team's record is refused naming the owning team | `team_forbidden` (`details.teamId`), `team_required`, `team_mismatch` | `resolve.py:49`, `check.py:203` |
| Scoped service tokens and API keys: a token does only what its scopes or key target say | `scope_required`, `event_not_owned`, `key_target`, `widget_key_other_deployment` | `check.py:212-247`, `services/agents-service/src/ops_agents/api/auth.py:272` |
| Embed origin from config: a widget serves only its deployment's allowed origins | `origin_required`, `origin_mismatch`, `origin_not_allowed` | `services/agents-service/src/ops_agents/api/widget_sessions.py:133-153` |
| Secrets hidden: no route returns a secret value; a team's secret never reaches another team or service | `secret_refused`; another team's secret is not found | `services/tools-service/src/ops_tools/store/secrets.py`, secrets |

## Roles

A person has roles per team through assignments: a membership role (`members.role`, kept equal to a built-in
assignment in the same transaction) or a grant, in one team or in every team (`*`), with an optional expiry
(`services/platform-service/src/ops_platform/store/tables.py`, migration `0006_roles`). What they may do in a team is
the union of their unexpired assignments there, `all` over `own`. The token carries team → role ids as the `access`
claim, each of those roles' stored cells as the `grids` claim (`ops_access.encode_grid`), and the tenant's
`perm_version`; every service reads them locally. A service also asks platform-service for the tenant's current
version (internal `GET /v1/permission-version`, for the tenant its service token names, cached for one second) and refuses an older token with
401 `permissions_changed`; the console renews the token and retries, so a role, grid, assignment or policy change
decides on the person's next request (`packages/ops_identity/src/ops_identity/resolve.py`, D62). When platform-service
does not answer, the last version seen, else the token, decides.

| Built-in role | Stored membership value | Meaning | Who holds it |
|---|---|---|---|
| Admin | `admin` | Every cell in the team. Security-team actions still need a role in the Security team | Team admins; Admin in `*` is a workspace admin who acts in any team |
| Builder | `builder` | Every cell in the team except people and access (members, roles, assignments) and the workspace's settings: connections, secrets and auth configs included (D59) | Team builders |
| Reviewer | `approver` (people read Reviewer) | Reads; decides the team's reviews; in the Security team, decides module security reviews | Team reviewers |
| Viewer | `viewer` | Reads the team's work, chats with its agents | Team viewers; every invite starts here |
| Security admin | (none; given with Admin in the Security team) | Egress, any team's secrets (naming the team), storage settings, module security reviews | Admins of the Security team (`builtin_roles_for`, `catalogue.py:187`) |
| Chat user | `chat_user` | Chats with the team's published agents and reads only their own threads | A first SSO sign-in; a grant |

The grid, generated from `ops_access` (`scripts/roles_matrix.py`; `make python-verify` fails when it is stale). Rows no
role holds are left out.

<!-- roles-matrix:begin (generated by scripts/roles_matrix.py from ops_access; do not edit) -->

`all`: every record in the team; `own`: records the person created or owns; `no`: refused.

| Area | Action | Admin | Builder | Reviewer | Viewer | Security admin | Chat user | Owner |
|---|---|---|---|---|---|---|---|---|
| agents | view | all | all | all | all | no | no | no |
| agents | create | all | all | no | no | no | no | no |
| agents | edit | all | all | no | no | no | no | no |
| agents | publish | all | all | no | no | no | no | no |
| agents | delete | all | all | no | no | no | no | no |
| agents | run | all | all | no | no | no | no | no |
| agents | decide | all | all | all | no | no | no | no |
| agents | manage | all | all | no | no | no | no | no |
| workflows | view | all | all | all | all | no | no | no |
| workflows | create | all | all | no | no | no | no | no |
| workflows | edit | all | all | no | no | no | no | no |
| workflows | publish | all | all | no | no | no | no | no |
| workflows | delete | all | all | no | no | no | no | no |
| workflows | run | all | all | no | no | no | no | no |
| workflows | decide | all | all | all | no | no | no | no |
| workflows | manage | all | all | no | no | no | no | no |
| skills | view | all | all | all | all | no | no | no |
| skills | create | all | all | no | no | no | no | no |
| skills | edit | all | all | no | no | no | no | no |
| skills | publish | all | all | no | no | no | no | no |
| skills | delete | all | all | own | own | no | no | no |
| skills | run | all | all | no | no | no | no | no |
| skills | decide | all | all | all | no | no | no | no |
| skills | manage | all | all | no | no | no | no | no |
| guardrails | view | all | all | all | all | no | no | no |
| guardrails | create | all | all | no | no | no | no | no |
| guardrails | edit | all | all | no | no | no | no | no |
| guardrails | publish | all | all | no | no | no | no | no |
| guardrails | delete | all | all | own | own | no | no | no |
| guardrails | run | all | all | no | no | no | no | no |
| guardrails | decide | all | all | all | no | no | no | no |
| guardrails | manage | all | all | no | no | no | no | no |
| widgets | view | all | all | all | all | no | no | no |
| widgets | create | all | all | no | no | no | no | no |
| widgets | edit | all | all | no | no | no | no | no |
| widgets | publish | all | all | no | no | no | no | no |
| widgets | delete | all | all | no | no | no | no | no |
| widgets | run | all | all | no | no | no | no | no |
| widgets | decide | all | all | all | no | no | no | no |
| widgets | manage | all | all | no | no | no | no | no |
| knowledge | view | all | all | all | all | no | no | no |
| knowledge | create | all | all | no | no | no | no | no |
| knowledge | edit | all | all | no | no | no | no | no |
| knowledge | publish | all | all | no | no | no | no | no |
| knowledge | delete | all | all | no | no | no | no | no |
| knowledge | run | all | all | no | no | no | no | no |
| knowledge | decide | all | all | no | no | no | no | no |
| knowledge | manage | all | all | no | no | no | no | no |
| tools | view | all | all | all | all | no | no | no |
| tools | create | all | all | no | no | no | no | no |
| tools | edit | all | all | no | no | no | no | no |
| tools | publish | all | all | no | no | no | no | no |
| tools | delete | all | all | no | no | no | no | no |
| tools | run | all | all | no | no | no | no | no |
| tools | decide | all | all | all | no | no | no | no |
| tools | manage | all | all | no | no | no | no | no |
| secrets_egress | view | all | all | all | all | all | no | no |
| secrets_egress | create | all | all | no | no | all | no | no |
| secrets_egress | edit | all | all | no | no | all | no | no |
| secrets_egress | publish | all | all | no | no | no | no | no |
| secrets_egress | delete | all | all | no | no | all | no | no |
| secrets_egress | run | all | all | no | no | no | no | no |
| secrets_egress | decide (Security team) | all | all | all | no | all | no | no |
| secrets_egress | manage (Security team) | all | all | no | no | all | no | no |
| connections | view | all | all | all | all | no | no | no |
| connections | create | all | all | no | no | no | no | no |
| connections | edit | all | all | no | no | no | no | no |
| connections | publish | all | all | no | no | no | no | no |
| connections | delete | all | all | no | no | no | no | no |
| connections | run | all | all | no | no | no | no | no |
| connections | decide | all | all | no | no | no | no | no |
| connections | manage | all | all | no | no | no | no | no |
| files | view | all | all | all | all | no | no | no |
| files | create | all | all | all | all | no | no | no |
| files | edit | all | all | no | no | no | no | no |
| files | publish | all | all | no | no | no | no | no |
| files | delete | all | all | all | all | no | no | no |
| files | run | all | all | no | no | no | no | no |
| files | decide | all | all | no | no | no | no | no |
| files | manage | all | all | no | no | no | no | no |
| documents | view | all | all | all | all | no | no | no |
| documents | create | all | all | no | no | no | no | no |
| documents | edit | all | all | all | all | no | no | no |
| documents | publish | all | all | no | no | no | no | no |
| documents | delete | all | all | no | no | no | no | no |
| documents | run | all | all | all | all | no | no | no |
| documents | decide | all | all | no | no | no | no | no |
| documents | manage | all | all | no | no | no | no | no |
| chat | view | all | all | own | own | no | own | no |
| chat | create | all | all | no | no | no | no | no |
| chat | edit | all | all | no | no | no | no | no |
| chat | publish | all | all | no | no | no | no | no |
| chat | delete | all | all | no | no | no | no | no |
| chat | run | all | all | all | all | no | all | no |
| chat | decide | all | all | all | no | no | no | no |
| chat | manage | all | all | no | no | no | no | no |
| memory | view | all | all | no | no | no | no | no |
| memory | create | all | all | no | no | no | no | no |
| memory | edit | own | own | own | own | no | own | no |
| memory | publish | all | all | no | no | no | no | no |
| memory | delete | all | all | no | no | no | no | no |
| memory | run | all | all | no | no | no | no | no |
| memory | decide | all | all | no | no | no | no | no |
| memory | manage | all | all | no | no | no | no | no |
| reviews | view | all | all | all | all | no | no | no |
| reviews | create | all | all | no | no | no | no | no |
| reviews | edit | all | all | no | no | no | no | no |
| reviews | publish | all | all | no | no | no | no | no |
| reviews | delete | all | all | no | no | no | no | no |
| reviews | run | all | all | no | no | no | no | no |
| reviews | decide | all | all | all | no | no | no | no |
| reviews | manage | all | all | no | no | no | no | no |
| cases | view | all | all | all | all | no | no | no |
| cases | create | all | all | all | all | no | no | no |
| cases | edit | all | all | all | all | no | no | no |
| cases | publish | all | all | no | no | no | no | no |
| cases | delete | all | all | no | no | no | no | no |
| cases | run | all | all | no | no | no | no | no |
| cases | decide | all | all | no | no | no | no | no |
| cases | manage | all | all | all | own | no | no | no |
| deployments | view | all | all | all | all | no | no | no |
| deployments | create | all | all | no | no | no | no | no |
| deployments | edit | all | all | no | no | no | no | no |
| deployments | publish | all | all | no | no | no | no | no |
| deployments | delete | all | all | no | no | no | no | no |
| deployments | run | all | all | no | no | no | no | no |
| deployments | decide | all | all | no | no | no | no | no |
| deployments | manage | all | all | no | no | no | no | no |
| settings | view (Security team) | all | no | no | no | all | no | no |
| settings | create | all | no | no | no | no | no | no |
| settings | edit | all | no | no | no | no | no | no |
| settings | publish | all | no | no | no | no | no | no |
| settings | delete | all | no | no | no | no | no | no |
| settings | run | all | no | no | no | no | no | no |
| settings | decide | all | no | no | no | no | no | no |
| settings | manage (Security team) | all | no | no | no | all | no | no |
| access | view | all | all | all | all | no | no | no |
| access | create | all | no | no | no | no | no | no |
| access | edit | all | no | no | no | no | no | no |
| access | publish | all | no | no | no | no | no | no |
| access | delete | all | no | no | no | no | no | no |
| access | run | all | no | no | no | no | no | no |
| access | decide | all | no | no | no | no | no | no |
| access | manage | all | no | no | no | no | no | no |
| audit | view | all | all | no | no | no | no | no |
| audit | create | all | all | no | no | no | no | no |
| audit | edit | all | all | no | no | no | no | no |
| audit | publish | all | all | no | no | no | no | no |
| audit | delete | all | all | no | no | no | no | no |
| audit | run | all | all | no | no | no | no | no |
| audit | decide | all | all | no | no | no | no | no |
| audit | manage | all | all | no | no | no | no | no |
| activity | view | all | all | all | no | all | no | no |
| activity | create | all | all | no | no | no | no | no |
| activity | edit | all | all | no | no | no | no | no |
| activity | publish | all | all | no | no | no | no | no |
| activity | delete | all | all | no | no | no | no | no |
| activity | run | all | all | no | no | no | no | no |
| activity | decide | all | all | no | no | no | no | no |
| activity | manage | all | all | no | no | no | no | no |
| webhooks | view | all | no | no | no | no | no | no |
| webhooks | create | all | no | no | no | no | no | no |
| webhooks | edit | all | no | no | no | no | no | no |
| webhooks | publish | all | no | no | no | no | no | no |
| webhooks | delete | all | no | no | no | no | no | no |
| webhooks | run | all | no | no | no | no | no | no |
| webhooks | decide | all | no | no | no | no | no | no |
| webhooks | manage | all | no | no | no | no | no | no |
| usage | view | all | no | no | no | no | no | no |
| usage | create | all | no | no | no | no | no | no |
| usage | edit | all | no | no | no | no | no | no |
| usage | publish | all | no | no | no | no | no | no |
| usage | delete | all | no | no | no | no | no | no |
| usage | run | all | no | no | no | no | no | no |
| usage | decide | all | no | no | no | no | no | no |
| usage | manage | all | no | no | no | no | no | no |
| workspace | manage | no | no | no | no | no | no | all |

<!-- roles-matrix:end -->

Every role's cells, built-in or custom, are the `role_permissions` rows platform-service stores. The grid above is
the seed: platform-service writes it for a new workspace and **Reset to default** puts a built-in role back to it.
A workspace admin edits any role but Admin on Access › Roles (`PUT /v1/roles/{id}/permissions`,
`POST /v1/roles/{id}/reset`, both audited as `role.edit` and `role.reset` and raising `perm_version`); Admin keeps
every cell (409 `admin_holds_every_cell`). `can()` decides from the token's `grids` claim, and platform-service from
the rows it reads at the moment of the check. A token minted without the claim (a test token, the dev header
caller) is answered from the seed.

## Policies

The catalogue is `packages/ops_access/src/ops_access/policies.py`. Values are stored per tenant in platform-service
(`policies`, migration `0011_policies`), each change audited, and read with `policy(p, key)` from the token or, for a
`live` policy, from `GET /v1/policies/{key}` on each decision. `PUT /v1/policies/{key}` checks the policy's
`changed_by` cell. Every default is pinned in `access-exceptions-allowlist.txt`, so a new policy or a changed default
fails the commit until it is classified.

| Key | Default | Open? | What on means | Changed by | Per team |
|---|---|---|---|---|---|
| `requesterMayDecide` | off | no (row E51) | The person who asked for, saved or started a decision may take it; off: 403 `own_request`. Set on Settings › Approvals, shown once review is on | `settings.manage` (Security team) | no (row E29) |
| `stepUp` | off | yes | Every approver steps up, besides operations that ask for it | `settings.manage` | no |
| `companySignInRequired` | off | yes | People on the workspace's verified company domains sign in only through its provider; the named break-glass Security admins (at most three) keep a password. Cannot turn on with nobody on the list (409 `break_glass_none`) | `settings.manage` | no |
| `mcpConnectionHours` | `8` hours, at most 720 (30 days) | yes | How long an assistant stays connected to a team's MCP address before the person signs in again; read when the person presses Allow, so a change reaches new connections | `settings.manage` | no |
| `chatThreadsOwnerOnly` | on | no (row E02) | A chat thread is read only by whoever started it, admins included | `settings.manage` | no |
| `publishReview` | `{}`: every area `major` | no (row E01) | Per team and area: `always`, `major` or `never` | `reviews.manage` | yes |
| `toolWritesNeedApproval` | Derived from `appChanges` for one release: on when the team asks a reviewer. A write to it lands in `appChanges` | yes | Read only; the decision comes from `appChanges` | `settings.manage`, because the write lands in `appChanges` | yes |
| `appWritesNeedApproval` | Derived from `appChangesByApp` for one release: the apps whose answer is a reviewer. A write lands in `appChangesByApp` | yes | Read only; the decision comes from `appChangesByApp` | `settings.manage` | yes |
| `appsChangeWithoutAsking` | Derived from `appChangesByApp` for one release: the apps whose answer is "none". A write lands in `appChangesByApp` | yes | Read only; the decision comes from `appChangesByApp` | `settings.manage` | yes |
| `appChanges` | `{}`: no team asks, so agents change apps without asking | yes | The team's one switch, "Ask before an agent changes anything in an app": off, ask the person (a confirmation only the asker answers), or ask a reviewer (a role that can decide reviews); `testAccountsNeverAsk` (on); `testRunsAsk` (on) | `settings.manage` | yes |
| `appChangesByApp` | `{}`: every app follows the team | yes | Per app: use the team setting, change without asking, ask the person, or ask a reviewer | `settings.manage` | yes |
| `aiSteps` | `{}`: off | no (row E03) | The team's workflows may use Classify, Summarise, Extract from text and Draft steps | `workflows.manage` | yes |
| `taskAssist` | `{}`: off | no (row E03) | A typed task opens with AI help | `workflows.manage` | yes |
| `checkBeforeSend` | `{}`: off | no (row E03) | Every write is checked against the team's sending policy first | `workflows.manage` | yes |
| `aiStepsMaskPersonalData` | `{}`: on | no (row E34) | People see SSNs, card and account numbers, emails and phones masked in AI steps' output and in document type examples | `workflows.manage` | yes |
| `pageImages` | `{}`: off | no (row E03) | The team's document types may show the model the page image of a scan or a doubtful field; a type turns it on under `documents.manage` | `settings.manage` (Security team) | yes |
| `egressNewHosts` | `ask_security` | no (row E48) | What happens when an app or tool names an address the account has not listed: ask Security, builders allow it, any public address, or only listed ones | `settings.manage` | yes |
| `securityTeamAddsSecrets` | off | yes | Only the Security team adds secrets | `settings.manage` | no |
| `memoryRetentionDays` | none | yes | How long agents keep what they remember about a person | `chat.manage` | no |
| `reviewSlaHours` | 8 | n/a | When a waiting publish review shows as overdue | `reviews.manage` | no |
| `extractionFloor` | 0.8 | n/a | The lowest confidence an extraction step accepts; a quality threshold, not an access rule | `settings.manage` | no |

Per-agent settings that decide what a person may do in a chat, saved with the agent's version and published through
its review:

| Setting | Default | What it decides | Changed by |
|---|---|---|---|
| `skillMenu` | `team` | Which skills a person may pick from the chat's / menu for one reply: `team` (any published team skill whose tools and knowledge bases the agent holds; the model may also load them on a match), `attached` (the agent's own skills), `off` (none; 422 `skill_menu_limit`). Picking needs `skills.view` in the conversation's team (403 `forbidden`) | `agents.edit`, on the agent's Skills tab |

## Approvals

Every approval behaviour is one of the settings below or the approve cell in the roles grid. The gateway's `needs`
expression (`services/tools-service/src/ops_tools/gateway_calls.py:448`) is the only place that decides whether a
write waits for a person; every setting in the table feeds it. Policies are changed in Settings › Policies or with
`PUT /v1/policies/{key}` (`services/platform-service/src/ops_platform/api/app.py:821`), and each change is audited.

| Setting | What it does | Default | Who changes it (cell) | Where | Code owner |
|---|---|---|---|---|---|
| The tool's own answer (`approvalMode`, `reviewerRole`) | Not set, don't ask, ask the person, or ask a reviewer (the role that reviews). Not set follows the app, then the team. A stored `requires_approval` is not read as an answer. A read never waits | Not set, so the app and team decide (the team default runs the write) | Whoever may edit the tool (`tools.edit`); loosening it is a major change, so a publish review applies (row E01) | Tools › the tool › operation › Access and approval; `PATCH /v1/tool-modules/{id}/operations/{op}` (`services/tools-service/src/ops_tools/modules/routes.py:196`) | `effective_answer`, `packages/ops_access/src/ops_access/policies.py`; the tool's part is read by `tool_mode`, `services/tools-service/src/ops_tools/modules/policy.py` |
| The team's answer for one tool (`appChangesByApp`, key `tool:<tool name>`) | Use the app's setting, don't ask, ask the person, or ask a reviewer. It replaces the tool's own answer above, so a plugin tool whose manifest asks first (its module row has no editor) can still be loosened | Not set, so the tool's own answer, then the app and team decide | A team admin (`settings.manage`), the same cell as the app and team answers | Tools › the tool › operation › "When an agent calls this tool"; `PUT /v1/policies/appChangesByApp` | `WriteApprovals.answer`, `services/tools-service/src/ops_tools/modules/policy.py`, then `effective_answer` |
| A test run's yes (`confirmed` on `POST /v1/tool-modules/{id}/test`) | The person who pressed Run answers a Real test run of a write on a live account, on the console's approval card. Honoured only on the console channel, only while the answer is "ask the person", and never for a reviewer's answer | Asked while "Test runs on live accounts ask first" is on | The person running it; the checkbox is the team admin's | Tools › the tool › Test panel | `GatewayCalls.call`, `services/tools-service/src/ops_tools/gateway_calls.py` |
| Ask before an agent changes anything in an app (`appChanges`, `appChangesByApp`) | Off: writes run. On: the person in the chat confirms (only the asker answers, row E50) or a reviewer chosen by role approves; nobody approves their own request unless `requesterMayDecide` is on. The most specific level wins: tool, then app, then team | Off, so writes run | A team admin (`settings.manage`) | Settings › Approvals | `packages/ops_access/src/ops_access/policies.py` (`effective_answer`, the one rule); `services/tools-service/src/ops_tools/gateway_calls.py` (`needs`) |
| Requester may decide (`requesterMayDecide`) | The person who asked for, saved or started a decision may also take it. Off: 403 `own_request` | Off (row E51) | A team admin (`settings.manage`) | Settings › Approvals, shown once review is on | `packages/ops_access/src/ops_access/policies.py:56`; applied in `can()`, `packages/ops_access/src/ops_access/check.py:171`; checked again when a write is sent, `asker_refusal` in `services/tools-service/src/ops_tools/modules/policy.py:88` |
| Tool writes need approval (`toolWritesNeedApproval`) | Derived from `appChanges`; read only. A write to it needs `settings.manage` (the code checks nothing else), and lands in `appChanges` | Off | `settings.manage` | Settings › Approvals | `services/platform-service/src/ops_platform/store/policies.py` |
| Apps whose writes need approval (`appWritesNeedApproval`) | Derived from `appChangesByApp`; read only | No app listed | Via `appChangesByApp` | Settings › Approvals | `services/platform-service/src/ops_platform/store/policies.py` |
| Approve cell (`reviews.decide`) | Who may decide a review at all. Without it a person cannot approve, whatever the policies say. A holder is not asked for their own write when approval is on | Held by the built-in Admin and Reviewer roles | An admin (`access.manage`) | Access › Roles; `PUT /v1/roles/{id}/permissions` (`services/platform-service/src/ops_platform/api/app.py:848`) | `packages/ops_access/src/ops_access/catalogue.py:94`; `approves_own_writes`, `services/tools-service/src/ops_tools/modules/policy.py:81` |
| Test accounts never ask (`testAccountsNeverAsk`, inside `appChanges`) | A write on an app's test account does not wait or ask, because it changes no live data | On | A team admin (`settings.manage`) | Settings › Approvals; the app's Accounts tab chooses the account | `effective_answer` (source `test-account`); `on_test_account`, `services/tools-service/src/ops_tools/gateway_calls.py` |
| Test runs ask first (`testRunsAsk`, inside `appChanges`) | A test run in the tool page of a write on a live account pauses for the person's yes. Chats and workflows keep their own answer; a test account never asks | On | A team admin (`settings.manage`) | `PUT /v1/policies/appChanges` (Settings › Approvals has the control) | `effective_answer` (channel `test`, source `test-run`); the test console, `ModuleService.test` in `services/tools-service/src/ops_tools/modules/service.py` |

One owner decides whether a write waits: `effective_answer`, called through the gateway's `needs()` in `gateway_calls.py`, the tool list, the test console and the chat. The person who asked is checked again live when the write is sent (`asker_refusal`, `modules/policy.py`), and every route that records an approval (`record_approval`, `services/agents-service/src/ops_agents/api/routers/reviews.py`) runs the same decider check. One rule is not a setting: every write over MCP waits for a person.

## Team and workspace scope

| Fact | Detail | Source |
|---|---|---|
| A team owns every asset | Agents, workflows, tools, knowledge bases and secrets belong to one team; teams are flat in v1 | — |
| The acting team | `X-Team-Id`, which must be one of the caller's teams; several teams and no header is 403 `team_required` | `resolve.py:43-50` |
| A record of another team | 404, the same as one that does not exist, with no team named; a record of another tenant is 404 | uc-526 |
| A record no team owns | None remain among a team's work: account records and the background processes, each named in `scripts/tests/test_team_boundary.py` | `scripts/tests/test_team_boundary.py` |
| A workspace admin | Admin in team `*`, acts in any team without joining it | — |
| Workspace settings | Policies are per tenant unless marked per team; a per-team value is changed in that team only | `policies.py` `per_team` |
| The Security team | The workspace's record (`tenants.security_team_id`, set on Settings > Workspace), carried in the token as `security_team`; `SECURITY_TEAM_ACTIONS` are held there whatever team the request acts in. A workspace that names none has no Security team: those actions are refused with 403 `no_security_team`. The install setting `security_team_id` only names a new workspace's team at bootstrap and in the dev seed | `catalogue.py:55`, `check.py:97`, migration `0029_tenant_security_team` |
| The default team for new people | A setting, read at first sign-in | — |
| Last admin | A team cannot lose its last admin | `services/platform-service/src/ops_platform/store/members.py:241` |

## Service principals and keys

| Caller | What it may do | Source |
|---|---|---|
| Person | The union of their roles' cells in the team | `check.py:106-200` |
| API key | Bound to one team; read-scoped keys only read; holds `workflows.run` (live runs, never test runs), `cases.manage` own and `tools.run` (the team's read tools over MCP); optionally pinned to one agent or workflow (`key_target`) | `KEY_GRANTS` `check.py:54` |
| Service token | Ed25519 signed, subject `service:<name>`; exactly the `area:action` scopes it lists; a team record needs the team in the token; a person's token passed through is checked as that person | `check.py:212`; [identity and tenancy](identity-and-tenancy.md) |
| Provisioning service | Holds `<area>:provision`; the only caller that sets `templateId` or `protection` | `require_provisioner`, `check.py:281` |
| Widget session | 15 minutes, bound to its deployment, origin and person; chats as that person; approves for no team | — |
| Dev header caller | Dev only; passes every role rule, on its own records only where a record has an owner; still bound by separation of duties. Acts in the one team its request names inside agents-service; at the request level elsewhere | `check.py:158` (row E09) |

API keys are created only by an admin of the team they are bound to (`access.create`), stored as a SHA-256 hash, and
shown once.

## Exceptions register

Every place a default is not open, or a refusal does not come from the grid or a policy. `Status` says whether the
exception stays (decided), is to go (to fix), or has no decision yet (no decision). Rows the script checks carry the same id in `access-exceptions-allowlist.txt`.

| Row | Exception | Code path | Decision | Date | Status |
|---|---|---|---|---|---|
| E01 | Publish reviews default to `major`: a first publish or a major change waits for a second person | `policies.py:69`; `publish_mode` | Major changes only is the default; never still reviews a security change | 2026-10-17 | decided |
| E02 | Chat threads are private by default; admins do not read the team's threads | `policies.py:80`; `check.py:112` | People's chats stay private; off lets admins read them | 2026-10-17 | decided |
| E03 | AI features are off per team: `aiSteps`, `taskAssist`, `checkBeforeSend`, `pageImages` | `policies.py:116-146` | Off by default, turned on through `can()` (`workflows.manage`; `settings.manage` in the Security team for `pageImages`) | 2026-10-18 | decided |
| E04 | Resolved 2026-11-05: built-in roles are edited like custom ones, every service decides from the stored rows the token carries, and Admin keeps every cell | `check.py` (`Access.scope`), `services/platform-service/src/ops_platform/roles.py` | Admins edit built-in roles' cells as a checkbox matrix | 2026-10-18 | resolved |
| E05 | A `system` record needs `<area>.manage` to edit or delete: roles holding manage, Builder and Admin by default (D59), and any role an admin ticks it on; tools-service's bulk delete asks the same `can()` per module | `check.py` (`_may_change_system`); `services/tools-service/src/ops_tools/modules/service.py` (`bulk_remove`) | Roles with `manage` change system records; the next provisioning run restores template fields. Was admins only until D59 | 2026-10-17 | decided; widened to roles with manage 2026-11-05 |
| E06 | `apply_access` runs only from the `tool_access_request` system workflow; system-only platform tools are kept out of modules | `services/tools-service/src/ops_tools/app.py:145,457-467`; `modules/review_events.py:17`; `registry.py:28,172` | Each such lock becomes a grid cell or a policy | 2026-10-18 | to fix |
| E07 | tools-service accepts a review decision only from `service:agents`, compared as a string | `modules/routes.py:227-228` | Becomes a scope check; the route goes when reviews run as workflows | 2026-10-18 | to fix |
| E08 | agents-service opens a tool module review for a person only beside `service:tools`'s token in `X-Service-Authorization`, compared as a string | `services/agents-service/src/ops_agents/api/tool_module_reviews.py:40-41` | The import route is deleted and tools-service's seed opens its waiting reviews with its own `tools:publish` token, which the scope cap gives tools-service only; the person path's string compare remains | 2026-10-18 | to fix |
| E09 | The dev header caller passes every role rule and skips the Security-team check | `check.py:158`; `services/agents-service/src/ops_agents/api/auth.py:84`; `packages/ops_store/src/ops_store/isolation.py:111` (its tenant-wide scope, reason `dev`); `services/tools-service/src/ops_tools/callers.py:34` | Accepted for dev only; `ops_identity` refuses dev headers elsewhere | 2026-10-16 | decided (dev only), under review |
| E10 | Separation of duties outside the grid: a step's `notDecidedBy`, and two money approvers who must differ | `services/agents-service/src/ops_agents/api/engine_reviews.py:503,696`; `routers/reviews.py:95` | Security sits in the step that acts; money needs two distinct approvers | 2026-10-18 | decided |
| E11 | tools-service reads `requesterMayDecide` itself instead of `can(requested_by=)` | `modules/service.py:1685` | The rule is decided; the second helper breaks "one helper per rule" | 2026-10-17 | to fix |
| E12 | Step-up is required for an operation that asks for it or needs two approvers, whatever `stepUp` says | `registry.py:39` | Every money decision verifies a step-up from the same person within five minutes | 2026-10-11 | decided |
| E13 | A refusal raised from a `can()` answer computed earlier (review teams, legal hold, and the `edits`, `manages` and `deletes` flags documents-service and files-service compute once per request and raise as typed errors) | `auth.py:202`; `services/files-service/src/ops_files/app.py:328`; `services/documents-service/src/ops_documents/app.py:127,278`, `document_types.py:162,233`; `services/files-service/src/ops_files/tenant_files.py:229,262,686` | Consistent with the grid (`reviews.decide`, `files.manage`); the legal hold answers `forbidden` where `role_required` is the code | 2026-10-17 | decided |
| E14 | Budget continue and stop: the thread's owner or `chat.manage`; raise: `chat.manage` | `services/agents-service/src/ops_agents/api/chat_budget.py:109,200,207,219` | Owner continues, a team admin raises; both now through `can()`, with codes `not_owner` and `admin_only` | 2026-10-17 | decided |
| E15 | Team isolation and key refusals raised without a baseline code | `services/tools-service/src/ops_tools/modules/directory.py:103`; `send_policy_routes.py:54` | Team isolation (baseline); an API key holds no sending-policy cell. The codes should be `team_forbidden` and `role_required` | 2026-10-17 | decided; codes to fix |
| E16 | Gateway refusals from a record's settings: approval token (OPA), amount limit, egress allow list, model alias sensitivity and image clearance | `services/tools-service/src/ops_tools/app.py:456`; `limits.py:38`; `mailboxes.py:269,300`; `services/models-service/src/ops_models/app.py:650` | Each comes from data an admin or builder edits through `can()`: the operation, the egress list, the alias version | 2026-10-11 to 2026-10-17 | decided |
| E17 | Store queries that read `members.role == "admin"`: the admin count shown per team, and re-mirroring Security admins when the Security team moves | `services/platform-service/src/ops_platform/store/teams.py:57`; `store/workspace.py:107` | Membership roles map to built-in assignments in the same transaction | 2026-10-17 | decided |
| E18 | An invite from an email domain outside the workspace's allowed domains is refused | `services/platform-service/src/ops_platform/teams.py:133` | `allowedDomains` is a sign-in policy setting; empty means any | 2026-10-16 | decided |
| E19 | The console decides by role name on the mock only (`useCanCheck` without `GET /v1/me/permissions`); nav pages name the grid cell they need (`lib/nav.ts` `needs`) | `apps/console/src/hooks/me-queries.ts:47` | The behaviour is decided; the mechanism goes to `GET /v1/me/permissions` | 2026-10-18 | to fix |
| E20 | The Access table styles the admin badge by role name | `apps/console/src/components/access/members-panel.tsx:53` | Presentation only; decides nothing | | consistent |
| E21 | `GET /v1/api-key-summaries` refused every person, workspace admins included | `services/platform-service/src/ops_platform/api/app.py` | Resolved 2026-10-19: a person with `can('access', 'manage')` in every team reads it; a service still needs `settings:view` (test_workspace_admin) | | **resolved** |
| E22 | The console maps team roles to a session role `admin`, `member` or `viewer` | `apps/console/src/lib/auth/providers/platform.ts:70` | No rule yet | | **no decision** |
| E23 | A tool write runs without approval unless the team turns approval on: every write (`toolWritesNeedApproval`), the apps it lists (`appWritesNeedApproval`) or one tool (its operation's switch); when on, a person holding reviews.decide in the team is not asked | `services/tools-service/src/ops_tools/gateway_calls.py` (`self_approved`); `modules/policy.py` `approves_own_writes` | Owner, 2026-11-01: approvals are off by default and role-based when on; superseded the 2026-10-17 default where every write waited. Superseded 2026-11-10 by E49 | 2026-11-01 | superseded |
| E24 | Models-service admin routes take a service token only; no person reaches them | `services/models-service/src/ops_models/app.py` | A prototype shortcut until the Govern models page | 2026-10-16 | to fix |
| E25 | Writes before a first publish: a draft test uses the draft, a live run needs the live version | `services/agents-service/src/ops_agents/api/auth.py:256-262` | A test run is a draft activity (`workflows.edit`); a live run is `workflows.run` | 2026-10-17 | decided |
| E26 | A team admin outside the Security team does not change egress, another team's secrets, storage settings or security reviews | `SECURITY_TEAM_ACTIONS` `catalogue.py:55` | These decide what every team may reach, so they are held in the Security team | 2026-10-17 | decided |
| E27 | An admin edits only their own memory (`memory.edit` own) | `catalogue.py:135` | What agents remember about a person is that person's to correct or forget | 2026-10-17 | decided |
| E28 | API keys hold three fixed cells in code rather than a role | `KEY_GRANTS` `check.py:56` | A key is a bank system acting for one team: live runs, cancelling its own, and running the team's tools over MCP (reads only; a write waits for a person, `gateway_calls.py`) | 2026-10-19 | decided |
| E29 | `requesterMayDecide` is one value per workspace | `policies.py:48` (no `per_team`) | It is a team policy | 2026-10-18 | to fix |
| E30 | A first SSO sign-in or an IdP group can give `chat_user`, `viewer`, `builder` or `approver`, never `admin`; and a first SSO sign-in never links by email to a person who is Admin of any team | `JIT_ROLES`, `services/platform-service/src/ops_platform/signin_settings.py:30`; `_holds_admin`, `services/platform-service/src/ops_platform/store/signin.py` | Owner, 2026-11-10 (SAML sign-in design, D5): Admin stays a person-to-person grant, so editing a group at the provider cannot make anyone an admin, and whoever controls the provider cannot sign in as an admin by naming their email; admins link from their own signed-in session | 2026-11-10 | decided |
| E31 | No invite or role change sets the `chat_user` membership; only a first SSO sign-in does | `catalogue.py:165-167`; invite roles in `apps/console/src/components/access/roles.ts` | An admin should be able to give someone Chat user; the mechanism has no rule yet | 2026-10-18 | **no decision** on the mechanism |
| E32 | Test threads need `agents.test`, which the code maps to `agents.edit`; no separate cell | `auth.py:239,256`; `services/agents-service/src/ops_agents/api/routers/chat.py:328` | Test threads are gated by `agents.test`, badged everywhere and kept out of counts and memory | 2026-10-18 | decided; separate cell not built |
| E33 | Anyone holding `connections.manage` may create shared connections | `connections` in `AREAS` (`packages/ops_access/src/ops_access/catalogue.py`); `connection_rights`, `services/tools-service/src/ops_tools/connections/service.py`; grid migration `0025_connections_cells` | Decided: admins hold it by default; every member reads (`connections.view`) | 2026-10-19 | built (1f1866c7) |
| E34 | `redactPii` masks what people see and defaults on; the model sees real values. AI steps follow the same decision through `aiStepsMaskPersonalData`, on unless a team sets false | `services/agents-service/src/ops_agents/api/agent_registry.py:39`; `packages/ops_access/src/ops_access/policies.py` (`aiStepsMaskPersonalData`, `team_off`) | Decided. An earlier wording, "masked in what the model sees", is superseded | 2026-10-19 | in review |
| E35 | A widget session approves for no team; the decision is made in Reviews | widget routes | Decided | 2026-10-17 | decided |
| E36 | Builder help and route by meaning have no policy yet; page images (`pageImages`) is uncommitted | `policies.py` | Off per team until turned on through `can()` | 2026-10-18 | not built |
| E37 | Credentials are entered only by a person in the console; outside dev, start refuses a credential still set in the environment | tools secrets, platform sign-in settings | Root signing keys stay in the environment | 2026-10-18 | decided |
| E38 | A seeded library widget answers 409 `seeded_widget` to an edit, whoever asks: it is locked by where it came from, not by a cell | `services/agents-service/src/ops_agents/api/routers/widgets.py:60` | A defect: seeded definitions are records editable through `can()`, never locked (owner's standing rule, 2026-10-18); the lock goes | 2026-10-19 | to fix |
| E39 | Check before sending fails closed: a `checkBeforeSend` platform-service cannot read counts as on, and a judge that cannot answer holds the write for a person (`NO_JUDGE`), so an outage never lets a write skip its check | `services/tools-service/src/ops_tools/modules/policy.py` (`CheckBeforeSend.on`); `send_check.py` | Writes wait for a person while the policy or the judge is unreachable; nothing goes out unchecked | 2026-10-19 | decided |
| E40 | The MCP server refused `/mcp/production/{team}` | — | Superseded 2026-11-03: the address is `/mcp/{team}` and every call over it is a test run, which uses an app's sandbox account when the team has one; a write still needs a person | 2026-11-03 | superseded |
| E41 | An API key is refused at a module's test console though it holds `tools.run` | `services/tools-service/src/ops_tools/modules/service.py` (`ModuleService.test`) | Keys hold `tools.run` for the gateway call path over MCP (E28), which logs and rate-limits each call; the test console is a person's and its reads are neither logged nor limited. Resolves once the test console's calls go through the logged, rate-limited gateway path | 2026-10-19 | to fix |
| E42 | The workspace's owner cannot leave it, or be removed or demoted on the member routes, until they transfer it (409 `owner_must_transfer`) | `services/platform-service/src/ops_platform/workspace_lifecycle.py` (`leave`, `refuse_owner`) | A workspace always has one owner; ownership itself is the grid cell `workspace.manage` held by the built-in role Owner, moved only by a transfer | 2026-10-23 | decided |
| E43 | A team's last active admin cannot leave it (409 `last_admin`) | `services/platform-service/src/ops_platform/workspace_lifecycle.py` (`leave_team`) | A team never exists without an admin, as the member routes already keep for a removal or demotion | 2026-10-23 | decided |
| E44 | A closed workspace refuses sign-in, sessions and service tokens to everyone but its owner (403 `workspace_closed`), whatever their roles | `services/platform-service/src/ops_platform/auth.py` (`start_session`); `workspace_lifecycle.py` (`closed`) | A deleted workspace stays restorable by its owner for the restore window and is closed to everyone else; the owner reaches only `/v1/me`, sign-in and Restore | 2026-10-23 | decided |
| E45 | A plugin's tool module answers 403 `plugin_module` to every edit, publish, delete, review request and access request, whoever asks: its tools change only when the installed plugin is upgraded | `services/tools-service/src/ops_tools/modules/service.py` (`_not_a_plugin`) | The module is system-held, as the platform's tools are; teams turn the plugin on or off instead | 2026-10-29 | prototype |
| E46 | The `plugins` policy (the install switch) | — | Superseded 2026-11-03: the policy is gone; an installed plugin is available to every team, which turns it on for itself, and settings fixed for every team come from the install config (`OPS_PLUGIN_LOCKED`) | 2026-11-03 | superseded |
| E47 | A members-only hosted form refuses anyone signed in outside the team that shares it, and answers the same for a form that does not exist (403 `form_members_only`) | `services/agents-service/src/ops_agents/api/routers/forms.py` (`_member_form`) | The form is the team's own start form shared with its members; reading it in another team would cross the team boundary, so a person outside it learns nothing about it | 2026-10-30 | prototype |
| E48 | `egressNewHosts` defaults to `ask_security`: a host the account has not listed waits for the Security team, unless the policy says builders, any public host or block; an unreadable policy counts as `ask_security` | `packages/ops_access/src/ops_access/policies.py`; `services/tools-service/src/ops_tools/egress.py` (`NewHosts`) | Reaching a new outside address is a security decision, so the default asks Security; private, loopback, link-local and metadata addresses are refused under every value | 2026-11-03 | prototype |
| E49 | `appsChangeWithoutAsking` defaults to no app listed, so a write in a chat runs without asking. When a team turns asking on, the person in the chat answers Allow, Deny or Allow for this chat; a write on a test account never asks, and a workflow or an agent run with nobody in it is not asked | `packages/ops_access/src/ops_access/policies.py`; `services/tools-service/src/ops_tools/gateway_calls.py` (`needs`, loosened by `app_changes_quietly`); `services/tools-service/src/ops_tools/app.py` (grantable operations carry the same answer in `requiresApproval`); `services/agents-service/src/ops_agents/graphs/agent_wrapper.py` | Writes run by default; asking is one team switch, designed and not yet built (the code keeps the separate fields). An unreadable list counts as off | 2026-11-10 | decided |
| E50 | A write whose app asks before changes is answered (Allow, Deny, Allow for this chat) only by the person who asked in the chat, whatever their role; an admin or reviewer cannot answer it for them, and a write any reviewer approval holds is decided as before | `services/agents-service/src/ops_agents/api/auth.py` (`require_asker`); `api/hitl_facade.py` (`_check_thread_decider`); `api/routers/reviews.py` (`record_approval`) | The answer is the person's consent to their own change, not an approval, so no grid cell grants it to anyone else | 2026-11-10 | decided |
| E51 | `requesterMayDecide` is off by default, so the person who asked for, saved or started a decision does not take it (403 `own_request`); a team loosens it by turning `requesterMayDecide` on | `packages/ops_access/src/ops_access/policies.py` (`requesterMayDecide`); `asker_refusal` in `services/tools-service/src/ops_tools/modules/policy.py`, through `can()`: an approval the asker gave themselves is checked against today's policy when the write is sent | Once review is on, nobody approves their own request, because a self-approval defeats the review | 2026-11-10 | decided |
| E52 | Decisions not yet on `can()`: GET routes no view cell decides (`open-read`), the roles grid evaluated outside `ops_access` (`grid-eval`), and roles read off the token by hand (`raw-role`). Listed at their count when the check began finding them, so a new one fails and the list only shrinks as each moves onto `can()` and `reader_of` | `scripts/check_access_exceptions.py`; `access-exceptions-allowlist.txt` | Each moves onto `can()`: reads on `reader_of(area)`, grid evaluation and role reads inside `ops_access` | 2026-11-12 | to fix |

## Access rules

The rules every access question is answered from. Code comments cite them by id (`D40`, `D59`); ids are kept, and a
retired id is not reused.

| # | Rule |
|---|---|
| D01 | People read the stored `approver` role as Reviewer. The stored and wire value is `approver` |
| D02 | Each team has one role model; built-in roles are data |
| D03 | A role comes from the verified token only (the `access` claim for the `X-Team-Id` team), never from a body, query or header the caller sets |
| D04 | A builder or admin of the owning team writes definitions; a reviewer decides; a viewer reads. Other callers get 403 `role_required` |
| D05 | Another team's record is refused with 403 `team_forbidden` naming the owning team; another tenant's record is 404 |
| D06 | Every record belongs to one team ([identity and tenancy](identity-and-tenancy.md#the-team-is-the-workspace)); whoever the grid lets change it in that team changes it |
| D07 | A builder or admin pauses an agent, as for workflows |
| D08 | A builder or admin starts a run, test or live; an API key of the team starts live runs only |
| D09 | Whoever started a run cancels it, or a reviewer or admin of the run's team |
| D10 | A reviewer or admin of the reviewing team decides a review, with separation of duties and step-up |
| D11 | Every role in an agent's team may chat with it; every agent belongs to one team |
| D12 | The console shows Decide or Cancel from the server: `canDecide` and `canCancel` on each record, filled by `can()` |
| D13 | Whoever holds `access.view` in a team checks another person's access there; a workspace admin does so in every team. The check runs the same `can()`, so policies show as reasons |
| D14 | The checked person is not told; each check is audited with who checked whom |
| D15 | Policies start at the defaults in [Policies](#policies) and [Approvals](#approvals): access policies are open and an admin switches stricter rules on; approvals are safe by default (row E51) |
| D16 | Admins do everything in their team; a workspace admin does so in every team |
| D17 | A refusal outside the grid and policies is a defect unless the [Exceptions register](#exceptions-register) records it |
| D18 | Definitions are database records seeded from files; built-in workflows, roles and task types are edited through `can()` and are never locked |
| D19 | Security for a definition lives in the step that acts (`notDecidedBy`, `requesterMayDecide`), never in a lock on the definition |
| D20 | `requesterMayDecide` is a team policy, off by default (row E51) |
| D21 | Separation of duties is part of `can()`, as `not_by` and `requested_by`; two-approver counting stays where approvals are counted |
| D22 | Admins see roles as a roles × permissions checkbox matrix and edit built-in roles' cells there |
| D23 | Chat user is a role that chats with the team's published agents and sees only its own threads |
| D24 | A control a person cannot use carries a ⓘ "why can't I" that names the missing cell or policy |
| D25 | Role tests go through invites and role changes, with `OPS_SEED_EVERYONE_ADMIN` off; the first seeded user is admin and builder for testing |
| D26 | An invite starts on Viewer |
| D27 | An invite lasts seven days, is single use, is made only by a team admin, shows its link once and sends no email |
| D28 | Test threads need `agents.test`, are badged everywhere and are kept out of counts, budgets and memory |
| D29 | Anyone holding `connections.manage` creates shared connections |
| D30 | AI features are off by default. Each is a team setting turned on through `can()`: AI steps, task assist, check before sending, builder help, page images to the model |
| D31 | `redactPii` masks what people see; it defaults on and the model sees real values |
| D32 | Only a person enters credentials, in the console. Root signing keys stay in the deployment's environment |
| D33 | Every tool secret belongs to a team and no service reads one; model provider keys are in an account-level store in models-service that account admins edit |
| D34 | A team owns its secrets: its builders add, change and remove them, unless `securityTeamAddsSecrets` is on |
| D35 | Knowledge is shared by the team: any builder changes or deletes its bases and sources |
| D36 | Chats are private by default (`chatThreadsOwnerOnly`); turned off, the team's admins read them |
| D37 | Only the person edits what agents remember about them |
| D38 | A Security-team rule is held by the Security team, a per-workspace setting; Admin in another team holds none of `SECURITY_TEAM_ACTIONS` |
| D39 | An assignment has a person or team subject, a role, a team or `*`, and an optional expiry; the permission version rises on every change, which applies on the next request (D62) |
| D40 | A custom role may be narrower than any built-in role and may not hold secrets, egress or Security-team cells |
| D41 | A service passes `can()` with `area:action` scopes in its token; otherwise 403 `scope_required` |
| D42 | People may call service routes, each with the cell it needs, answering their team's records only |
| D43 | An approver or admin of the Security team decides a module security review for a security change, of the module's team otherwise; never the requester or saver |
| D44 | The module's team decides a tool access request in Human Tasks, with the same requester policy and step-up; the module's builders and admins revoke grants |
| D45 | A tools review run is owned by the deciding team; `created_by` is who asked, so the requester rule applies |
| D46 | Publishes wait for review per team and area: always, major (default) or never; a security change is always reviewed by Security; an unreadable policy waits |
| D47 | A builder or admin of the agent's team makes a widget deployment; a person reaches it with a 15-minute session from the customer's SSO token or a team key, bound to deployment, origin and person |
| D48 | A widget session does not approve; the decision is made in Reviews |
| D49 | A team admin creates API keys; tokens live 15 minutes, sessions 8 hours; revocation reaches other services within 15 minutes |
| D50 | The thread's owner continues a spent chat budget; a team admin raises it |
| D51 | Whoever holds `files.create` in the team changes document types; others see those pages read only |
| D52 | An admin of the Security team changes storage settings; every save is audited |
| D53 | A secret's team scope is enforced in the gateway: a call reads only its own team's secret (one team per secret, no scopes); a secret in use cannot be deleted |
| D54 | A platform admin or the command line provisions a workspace; `system` records need `manage`, `managed` records change freely and template fields come back on the next provisioning run |
| D55 | Teams are flat and created by a workspace admin; the Security team and the default team are settings |
| D56 | The extraction floor is a quality threshold with the engine's default, outside access |
| D57 | A password account steps up with password plus TOTP when enrolled; SSO and Google accounts step up at their IdP |
| D58 | A money approval needs two distinct approvers when the operation says so, each with a step-up under five minutes old |
| D59 | Builder holds every cell in the team except people and access (members, roles, assignments) and the workspace's settings: connections, secrets, auth configs and testing a connection included. Admin holds every cell |
| D60 | Role permissions live in the database. A workspace admin edits any role's cells on Access › Roles, built-in or custom, each change audited; the code grid is seed data, with Reset to default per built-in role |
| D61 | An auth config's client secret is changed on its auth config only. The Secrets page lists it read only with a link to the config, and the secrets API refuses a rotate or delete of it (409 `credential_secret`) naming the config |
| D62 | A change to roles, cells, assignments or policies reaches the services on the person's next request: each service compares the token's `perm_version` with platform-service's current one and refuses an older token (401 `permissions_changed`), so the client renews it. The database is the one source; the token is a copy checked by version |
| D63 | Each workspace's Security team is held on its own record, edited by a workspace admin through `can()` on Settings › Workspace and read by every service from the token, or from platform-service for a review a service opened. The install setting names only a new workspace's team |
| D64 | The install sends its own mail (password resets, a `send_reply` that names no mailbox) with its own provider and password from the environment; a team reads and sends mail only through its mailbox records, each with its own secret. No setting names a mailbox or a team's secret |
| D65 | A model call uses the provider key of the account it names (`X-Tenant-Id`, which every calling service sends); a call that uses an account's key without naming one is refused, 400 `tenant_required` |
| D66 | A workspace's sign-in secrets are kept in the workspace, sealed under the install's secrets key: a Security team admin saves or deletes one through `can()` (`settings.manage`), each change audited, and a provider names it as `clientSecretRef`; no value is read back, and one a provider names is not deleted (409 `secret_in_use`) |
| D67 | A workspace admin creates a custom role from scratch or as a copy (less the cells D40 keeps from custom roles), renames, edits and deletes it on Access › Roles; a delete names the holders and moves them to another role. An admin of a team gives a person a custom role in that team on Access › People; a built-in role comes with the team role. Every change goes through `can()` and is audited (`role.create`, `role.rename`, `role.delete`, `role.grant`, `role.ungrant`) |

## Errors

| Status and code | When |
|---|---|
| 401 | No valid token or key |
| 403 `role_required` | The caller's roles lack the cell; `details` names `teamId`, `area`, `action`, `roles` and `grantedBy` |
| 403 `own_request` | The person who asked, saved or started what is decided, while `requesterMayDecide` is off, or an earlier approver of a two-person decision |
| 403 `not_decided_by` | The step names this person in `notDecidedBy` |
| 403 `system_record` | A `system` record changed without `<area>.manage` (E05) |
| 403 `team_forbidden`, `team_required`, `scope_required` | The baseline (see above) |
| 403 `admin_required` | platform-service's older code for a missing `access` or `audit` cell |
| 404 | Another tenant's record |

Read routes: `GET /v1/roles`, `GET /v1/roles/{id}`, `GET /v1/me/permissions`, `GET /v1/people/{id}/permissions`,
`GET /v1/access/holders`, `GET /v1/policies`, `GET /v1/policies/{key}`; write: `PUT /v1/policies/{key}` and the member
routes (APIs).

## Reusable parts

Built by the Access page for any page that adds people to a team or reads their roles; listed in the UI
component registry.

| Part | Path | Use it for |
|---|---|---|
| `InviteDialog` | `apps/console/src/components/shared/invite-dialog.tsx` | Inviting people by email with one role; saves as one form and says no email is sent. Pass `teams` only where the service invites to a picked team; platform-service invites to the team in `X-Team-Id` |
| `InviteLinksDialog` | `apps/console/src/components/shared/invite-links-dialog.tsx` | Showing the links of the invitations just made, once, each with a copy button; the service keeps only a hash |
| `MEMBER_ROLES`, `roleLabel` | `apps/console/src/components/access/roles.ts` | The roles with the name people read ("Reviewer" for the stored `approver`) and a one-line description; the invite, the role change and the role facet read it |
| `useTeamRole()` | `apps/console/src/hooks/me-queries.ts` | Offering an action to the roles that may take it (Invite, Export of the audit log, legal holds) |

An empty review queue or the team switcher that offers "Invite a reviewer" opens `InviteDialog` and then
`InviteLinksDialog` with the result of `useInviteMembers()`; `MembersPanel` is the Access page's own list and is not
for reuse.

## Keeping this page true

| Check | Runs | Fails when |
|---|---|---|
| `scripts/roles_matrix.py --check` | `make python-verify` | The grid above differs from `ops_access` |
| `scripts/check_access_exceptions.py` | Every commit (`scripts/verify-staged.sh`) and `make python-verify` | A 403, a role-name comparison, a system lock or a policy default appears that `access-exceptions-allowlist.txt` does not list against a register row, or a listed one is gone and its line was not lowered |
| `scripts/tests/test_builtin_roles_match_checks.py` | `make python-verify` | A service's check answers a cell differently from the grid |
| Access check | Each architecture review, and each question about access | A change, question or diff conflicts with this page, or asks something [Access rules](#access-rules) answers |

A new rule adds a row to Access rules in the same change that acts on it; a new exception adds a register
row and an allowlist line with a `Standards-exception:` trailer.
