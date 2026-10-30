# Roles and permissions

Status: current, 2026-10-19. This is the one page for who may do what in Ops AI. Before asking the maintainers an access
question, look it up in [Decided questions](#decided-questions); before writing a refusal, a role check, a lock or a
closed default, look it up in the [Exceptions register](#exceptions-register). Code is cited at commit `c96319da`.
The grid below is generated from `packages/ops_access` and checked by `make python-verify`; the register is checked by
`scripts/check_access_exceptions.py` on every commit: every 403 (typed errors included) and every 409 code against a
line of `access-exceptions-allowlist.txt`, every line's row against this register (a resolved row holds no lines; a
line added on a row with no decision fails, and the lines already on one are printed for the maintainers), and every
exception line added since the list began against a `Standards-exception:` trailer on its commit that says
`approved by the orchestrator`. The agent brief that compares new cards and diffs with this page
is access check.

## How access is decided

Every access decision is one call, `ops_access.can(principal, area, action, team=, owner=, not_by=, requested_by=)`
(`packages/ops_access/src/ops_access/check.py:127`). It answers from two sources and nothing else:

| Source | What it holds | Who changes it |
|---|---|---|
| The roles grid | Role × (area, action) cells, scope `all` or `own`; a person holds roles per team through assignments | Admins (`access` cells) |
| Govern › Policies | Stricter rules a workspace or team switches on, each with an open default | Whoever holds the policy's `changed_by` cell |

The maintainers' rules for both (2026-10-17 to 2026-10-19, CLAUDE.md "No hard coding"):

| Rule | Consequence |
|---|---|
| Defaults are open | A new workspace meets no control until an admin sets one. A stricter rule is an opt-in setting |
| Admins can do everything | The built-in Admin role holds every cell in its team (migration `0016_admin_every_cell`). The exceptions are rows E02, E26 and E27 |
| A refusal behind neither the grid nor a policy is a defect | Unless the [Exceptions register](#exceptions-register) records the maintainers' decision for it |
| Definitions are database records | Built-in workflows, roles and task types are seeded and editable through `can()`, never locked in code |
| Security sits in the step that acts | Separation of duties is a step setting (`notDecidedBy`) and a team policy (`requesterMayDecide`), never a lock on a definition |
| AI features are off by default | The documented exception to open defaults (rows E03, E36) |

### The always-on baseline

These hold whatever the grid and policies say. A 403 with one of these codes needs no register row
(`BASELINE` in `scripts/check_access_exceptions.py`).

| Control | Codes | Where |
|---|---|---|
| Token identity: every caller is a verified token, key or service token; dev headers only in dev | 401, `api_key_refused`, `not_the_invitee`, `key_not_registered` | `packages/ops_identity/src/ops_identity/resolve.py`, `fastapi.py:13` |
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
claim and the tenant's `perm_version`; every service reads it locally, so a change applies at the next token refresh.

| Built-in role | Stored membership value | Meaning | Who holds it |
|---|---|---|---|
| Admin | `admin` | Every cell in the team. Security-team actions still need a role in the Security team | Team admins; Admin in `*` is a workspace admin who acts in any team |
| Builder | `builder` | Reads the team's work; creates, edits, tests and publishes its definitions | Team builders |
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
| agents | decide | all | no | all | no | no | no | no |
| agents | manage | all | no | no | no | no | no | no |
| workflows | view | all | all | all | all | no | no | no |
| workflows | create | all | all | no | no | no | no | no |
| workflows | edit | all | all | no | no | no | no | no |
| workflows | publish | all | all | no | no | no | no | no |
| workflows | delete | all | all | no | no | no | no | no |
| workflows | run | all | all | no | no | no | no | no |
| workflows | decide | all | no | all | no | no | no | no |
| workflows | manage | all | no | no | no | no | no | no |
| skills | view | all | all | all | all | no | no | no |
| skills | create | all | all | no | no | no | no | no |
| skills | edit | all | all | no | no | no | no | no |
| skills | publish | all | all | no | no | no | no | no |
| skills | delete | all | own | own | own | no | no | no |
| skills | run | all | no | no | no | no | no | no |
| skills | decide | all | no | all | no | no | no | no |
| skills | manage | all | no | no | no | no | no | no |
| guardrails | view | all | all | all | all | no | no | no |
| guardrails | create | all | all | no | no | no | no | no |
| guardrails | edit | all | all | no | no | no | no | no |
| guardrails | publish | all | all | no | no | no | no | no |
| guardrails | delete | all | own | own | own | no | no | no |
| guardrails | run | all | no | no | no | no | no | no |
| guardrails | decide | all | no | all | no | no | no | no |
| guardrails | manage | all | no | no | no | no | no | no |
| widgets | view | all | all | all | all | no | no | no |
| widgets | create | all | all | no | no | no | no | no |
| widgets | edit | all | all | no | no | no | no | no |
| widgets | publish | all | all | no | no | no | no | no |
| widgets | delete | all | no | no | no | no | no | no |
| widgets | run | all | no | no | no | no | no | no |
| widgets | decide | all | no | all | no | no | no | no |
| widgets | manage | all | no | no | no | no | no | no |
| knowledge | view | all | all | all | all | no | no | no |
| knowledge | create | all | all | no | no | no | no | no |
| knowledge | edit | all | all | no | no | no | no | no |
| knowledge | publish | all | no | no | no | no | no | no |
| knowledge | delete | all | all | no | no | no | no | no |
| knowledge | run | all | no | no | no | no | no | no |
| knowledge | decide | all | no | no | no | no | no | no |
| knowledge | manage | all | no | no | no | no | no | no |
| tools | view | all | all | all | all | no | no | no |
| tools | create | all | all | no | no | no | no | no |
| tools | edit | all | all | no | no | no | no | no |
| tools | publish | all | all | no | no | no | no | no |
| tools | delete | all | all | no | no | no | no | no |
| tools | run | all | all | no | no | no | no | no |
| tools | decide | all | no | all | no | no | no | no |
| tools | manage | all | no | no | no | no | no | no |
| secrets_egress | view | all | all | all | all | all | no | no |
| secrets_egress | create | all | all | no | no | all | no | no |
| secrets_egress | edit | all | all | no | no | all | no | no |
| secrets_egress | publish | all | no | no | no | no | no | no |
| secrets_egress | delete | all | all | no | no | all | no | no |
| secrets_egress | run | all | no | no | no | no | no | no |
| secrets_egress | decide (Security team) | all | no | all | no | all | no | no |
| secrets_egress | manage (Security team) | all | no | no | no | all | no | no |
| connections | view | all | all | all | all | no | no | no |
| connections | create | all | no | no | no | no | no | no |
| connections | edit | all | no | no | no | no | no | no |
| connections | publish | all | no | no | no | no | no | no |
| connections | delete | all | no | no | no | no | no | no |
| connections | run | all | no | no | no | no | no | no |
| connections | decide | all | no | no | no | no | no | no |
| connections | manage | all | no | no | no | no | no | no |
| files | view | all | all | all | all | no | no | no |
| files | create | all | all | all | all | no | no | no |
| files | edit | all | no | no | no | no | no | no |
| files | publish | all | no | no | no | no | no | no |
| files | delete | all | all | all | all | no | no | no |
| files | run | all | no | no | no | no | no | no |
| files | decide | all | no | no | no | no | no | no |
| files | manage | all | no | no | no | no | no | no |
| documents | view | all | all | all | all | no | no | no |
| documents | create | all | no | no | no | no | no | no |
| documents | edit | all | all | all | all | no | no | no |
| documents | publish | all | no | no | no | no | no | no |
| documents | delete | all | no | no | no | no | no | no |
| documents | run | all | all | all | all | no | no | no |
| documents | decide | all | no | no | no | no | no | no |
| documents | manage | all | no | no | no | no | no | no |
| chat | view | all | own | own | own | no | own | no |
| chat | create | all | no | no | no | no | no | no |
| chat | edit | all | no | no | no | no | no | no |
| chat | publish | all | no | no | no | no | no | no |
| chat | delete | all | no | no | no | no | no | no |
| chat | run | all | all | all | all | no | all | no |
| chat | decide | all | no | all | no | no | no | no |
| chat | manage | all | no | no | no | no | no | no |
| memory | view | all | no | no | no | no | no | no |
| memory | create | all | no | no | no | no | no | no |
| memory | edit | own | own | own | own | no | own | no |
| memory | publish | all | no | no | no | no | no | no |
| memory | delete | all | no | no | no | no | no | no |
| memory | run | all | no | no | no | no | no | no |
| memory | decide | all | no | no | no | no | no | no |
| memory | manage | all | no | no | no | no | no | no |
| reviews | view | all | all | all | all | no | no | no |
| reviews | create | all | no | no | no | no | no | no |
| reviews | edit | all | no | no | no | no | no | no |
| reviews | publish | all | no | no | no | no | no | no |
| reviews | delete | all | no | no | no | no | no | no |
| reviews | run | all | no | no | no | no | no | no |
| reviews | decide | all | no | all | no | no | no | no |
| reviews | manage | all | no | no | no | no | no | no |
| cases | view | all | all | all | all | no | no | no |
| cases | create | all | all | all | all | no | no | no |
| cases | edit | all | all | all | all | no | no | no |
| cases | publish | all | no | no | no | no | no | no |
| cases | delete | all | no | no | no | no | no | no |
| cases | run | all | no | no | no | no | no | no |
| cases | decide | all | no | no | no | no | no | no |
| cases | manage | all | own | all | own | no | no | no |
| deployments | view | all | all | all | all | no | no | no |
| deployments | create | all | all | no | no | no | no | no |
| deployments | edit | all | all | no | no | no | no | no |
| deployments | publish | all | no | no | no | no | no | no |
| deployments | delete | all | no | no | no | no | no | no |
| deployments | run | all | all | no | no | no | no | no |
| deployments | decide | all | no | no | no | no | no | no |
| deployments | manage | all | no | no | no | no | no | no |
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
| audit | view | all | no | no | no | no | no | no |
| audit | create | all | no | no | no | no | no | no |
| audit | edit | all | no | no | no | no | no | no |
| audit | publish | all | no | no | no | no | no | no |
| audit | delete | all | no | no | no | no | no | no |
| audit | run | all | no | no | no | no | no | no |
| audit | decide | all | no | no | no | no | no | no |
| audit | manage | all | no | no | no | no | no | no |
| workspace | manage | no | no | no | no | no | no | all |

<!-- roles-matrix:end -->

Built-in grids are answered from code (`check.py:73`), not from the `role_permissions` rows platform-service stores;
custom roles are fetched from those rows. Editing a built-in role's cells is decided and not built (row E04).

## Policies

The catalogue is `packages/ops_access/src/ops_access/policies.py`. Values are stored per tenant in platform-service
(`policies`, migration `0011_policies`), each change audited, and read with `policy(p, key)` from the token or, for a
`live` policy, from `GET /v1/policies/{key}` on each decision. `PUT /v1/policies/{key}` checks the policy's
`changed_by` cell. Every default is pinned in `access-exceptions-allowlist.txt`, so a new policy or a changed default
fails the commit until it is classified.

| Key | Default | Open? | What on means | Changed by | Per team | Decision |
|---|---|---|---|---|---|---|
| `requesterMayDecide` | on | yes | The person who asked for, saved or started a decision may take it; off: 403 `own_request` | `settings.manage` (Security team) | no (row E29) | an earlier change; owner 2026-10-18: a team policy |
| `stepUp` | off | yes | Every approver steps up, besides operations that ask for it | `settings.manage` | no | an earlier change |
| `chatThreadsOwnerOnly` | on | no (row E02) | A chat thread is read only by whoever started it, admins included | `settings.manage` | no | Owner via orchestrator 2026-10-17 |
| `publishReview` | `{}`: every area `major` | no (row E01) | Per team and area: `always`, `major` or `never` | `reviews.manage` | yes | an earlier change Q1, an earlier change |
| `toolWritesNeedApproval` | `{}`: off | yes | Every tool write of the team waits for a person, including those an operation lets run at once | `reviews.manage` | yes | an earlier change |
| `aiSteps` | `{}`: off | no (row E03) | The team's workflows may use Classify, Summarise, Extract from text and Draft steps | `workflows.manage` | yes | Owner 2026-10-18, an earlier change |
| `taskAssist` | `{}`: off | no (row E03) | A typed task opens with AI help | `workflows.manage` | yes | Owner 2026-10-18, an earlier change |
| `checkBeforeSend` | `{}`: off | no (row E03) | Every write is checked against the team's sending policy first | `workflows.manage` | yes | Owner 2026-10-18, an earlier change |
| `aiStepsMaskPersonalData` | `{}`: on | no (row E34) | People see SSNs, card and account numbers, emails and phones masked in AI steps' output and in document type examples | `workflows.manage` | yes | Owner 2026-10-19, an earlier change; an earlier change |
| `pageImages` | `{}`: off | no (row E03) | The team's document types may show the model the page image of a scan or a doubtful field; a type turns it on under `documents.manage` | `settings.manage` (Security team) | yes | Owner 2026-10-18, an earlier change |
| `securityTeamAddsSecrets` | off | yes | Only the Security team adds secrets | `settings.manage` | no | Owner 2026-10-17 |
| `memoryRetentionDays` | none | yes | How long agents keep what they remember about a person | `chat.manage` | no | Owner 2026-10-17 |
| `reviewSlaHours` | 8 | n/a | When a waiting publish review shows as overdue | `reviews.manage` | no | an earlier change |
| `extractionFloor` | 0.8 | n/a | The lowest confidence an extraction step accepts; a quality threshold, not an access rule | `settings.manage` | no | Owner via orchestrator 2026-10-17 |

## Team and workspace scope

| Fact | Detail | Source |
|---|---|---|
| A team owns every asset | Agents, workflows, tools, knowledge bases and secrets belong to one team; teams are flat in v1 | an earlier change (owner 2026-10-17) |
| The acting team | `X-Team-Id`, which must be one of the caller's teams; several teams and no header is 403 `team_required` | `resolve.py:43-50` |
| A record of another team | 404, the same as one that does not exist, with no team named; a record of another tenant is 404 | an earlier change (owner's answer Q4 of the team-boundary interview), uc-526 |
| A record no team owns | None remain among a team's work: account records and the background processes, each named in `scripts/tests/test_team_boundary.py` | an earlier change |
| A workspace admin | Admin in team `*`, acts in any team without joining it | an earlier change |
| Workspace settings | Policies are per tenant unless marked per team; a per-team value is changed in that team only | `policies.py` `per_team` |
| The Security team | A setting per workspace, carried in the token as `security_team`; `SECURITY_TEAM_ACTIONS` are held there whatever team the request acts in | `catalogue.py:55`, `check.py:95` |
| The default team for new people | A setting, read at first sign-in | an earlier change |
| Last admin | A team cannot lose its last admin | `services/platform-service/src/ops_platform/store/members.py:241` |

## Service principals and keys

| Caller | What it may do | Source |
|---|---|---|
| Person | The union of their roles' cells in the team | `check.py:106-200` |
| API key | Bound to one team; read-scoped keys only read; holds `workflows.run` (live runs, never test runs), `cases.manage` own and `tools.run` (the team's read tools over MCP); optionally pinned to one agent or workflow (`key_target`) | `KEY_GRANTS` `check.py:54`; an earlier change Q1; an earlier change Q2; an earlier change |
| Service token | Ed25519 signed, subject `service:<name>`; exactly the `area:action` scopes it lists; a team record needs the team in the token; a person's token passed through is checked as that person | `check.py:212`; an earlier change Q3; [identity and tenancy](identity-and-tenancy.md) |
| Provisioning service | Holds `<area>:provision`; the only caller that sets `templateId` or `protection` | `require_provisioner`, `check.py:281`; an earlier change |
| Widget session | 15 minutes, bound to its deployment, origin and person; chats as that person; approves for no team | an earlier change Q2, an earlier change Q3 |
| Dev header caller | Dev only; passes every role rule, on its own records only where a record has an owner; still bound by separation of duties. Acts in the one team its request names inside agents-service; at the request level from an earlier change | `check.py:158` (row E09) |

API keys are created only by an admin of the team they are bound to (`access.create`), stored as a SHA-256 hash, and
shown once (an earlier change Q5).

## Exceptions register

Every place a default is not open, or a refusal does not come from the grid or a policy. `Status` says whether the
owner decided it stays (decided), decided it goes (to fix, with the card), or never decided it (no decision: these go
to the maintainers). Rows the script checks carry the same id in `access-exceptions-allowlist.txt`.

| Row | Exception | Code path | Decision | Date | Source | Status |
|---|---|---|---|---|---|---|
| E01 | Publish reviews default to `major`: a first publish or a major change waits for a second person | `policies.py:69`; `publish_mode` | Major changes only is the default; never still reviews a security change | 2026-10-17 | an earlier change Q1, an earlier change, an earlier change | decided |
| E02 | Chat threads are private by default; admins do not read the team's threads | `policies.py:80`; `check.py:112` | People's chats stay private; off lets admins read them | 2026-10-17 | owner via orchestrator, `policies.py:80` | decided |
| E03 | AI features are off per team: `aiSteps`, `taskAssist`, `checkBeforeSend`, `pageImages` | `policies.py:116-146` | Off by default, turned on through `can()` (`workflows.manage`; `settings.manage` in the Security team for `pageImages`) | 2026-10-18 | owner; an earlier change to an earlier change Q3; an earlier change | decided |
| E04 | Built-in roles cannot be edited: `/v1/roles` is read only, and built-in grids answer from code, so an edited `role_permissions` row would change no decision | `check.py:73`; `services/platform-service/src/ops_platform/api/app.py:390-400` | Admins edit built-in roles' cells as a checkbox matrix | 2026-10-18 | owner via orchestrator; an earlier change | to fix |
| E05 | A `system` record needs `<area>.manage` (admins) to edit or delete; tools-service's bulk delete asks the same `can()` per module (tick 30) | `check.py:151`; `services/tools-service/src/ops_tools/modules/service.py` (`bulk_remove`) | `check.py`: admins may change system records, the next provisioning run restores template fields. The bulk-delete refusal of admins was removed under the maintainers' rule that admins do everything (the orchestrator 2026-10-19) | 2026-10-17 | an earlier change Q3, migration `0012_system_records`; an earlier change | decided; the bulk-delete refusal removed in cad384d1 |
| E06 | `apply_access` runs only from the `tool_access_request` system workflow; system-only platform tools are kept out of modules | `services/tools-service/src/ops_tools/app.py:145,457-467`; `modules/review_events.py:17`; `registry.py:28,172` | Each such lock becomes a grid cell or a policy | 2026-10-18 | shortcut audit; an earlier change | to fix |
| E07 | tools-service accepts a review decision only from `service:agents`, compared as a string | `modules/routes.py:227-228` | Becomes a scope check; the route goes when reviews run as workflows | 2026-10-18 | an earlier change; an earlier change | to fix |
| E08 | agents-service opens a tool module review for a person only beside `service:tools`'s token in `X-Service-Authorization`, compared as a string | `services/agents-service/src/ops_agents/api/tool_module_reviews.py:40-41` | The import route is deleted and tools-service's seed opens its waiting reviews with its own `tools:publish` token, which the scope cap gives tools-service only; the person path's string compare remains for an earlier change | 2026-10-18 | an earlier change Q2; an earlier change Q3 | to fix |
| E09 | The dev header caller passes every role rule and skips the Security-team check | `check.py:158`; `services/agents-service/src/ops_agents/api/auth.py:84`; `packages/ops_store/src/ops_store/isolation.py:111` (its tenant-wide scope, reason `dev`); `services/tools-service/src/ops_tools/callers.py:34` | Accepted for dev only; `ops_identity` refuses dev headers elsewhere | 2026-10-16 | review of an earlier change; an earlier change lists it | decided (dev only), under review in an earlier change |
| E10 | Separation of duties outside the grid: a step's `notDecidedBy`, and two money approvers who must differ | `services/agents-service/src/ops_agents/api/engine_reviews.py:503,696`; `routers/reviews.py:95` | Security sits in the step that acts; money needs two distinct approvers | 2026-10-18 | owner; ADR-0005; R9 | decided |
| E11 | tools-service reads `requesterMayDecide` itself instead of `can(requested_by=)` | `modules/service.py:1685` | The rule is decided; the second helper breaks "one helper per rule" | 2026-10-17 | an earlier change; review checklist §1 | to fix |
| E12 | Step-up is required for an operation that asks for it or needs two approvers, whatever `stepUp` says | `registry.py:39` | Every money decision verifies a step-up from the same person within five minutes | 2026-10-11 | sign-in and sessions 3.7; ADR-0005 | decided |
| E13 | A refusal raised from a `can()` answer computed earlier (review teams, legal hold, and the `edits`, `manages` and `deletes` flags documents-service and files-service compute once per request and raise as typed errors) | `auth.py:202`; `services/files-service/src/ops_files/app.py:328`; `services/documents-service/src/ops_documents/app.py:127,278`, `document_types.py:162,233`; `services/files-service/src/ops_files/tenant_files.py:229,262,686` | Consistent with the grid (`reviews.decide`, `files.manage`); the legal hold answers `forbidden` where `role_required` is the code | 2026-10-17 | an earlier change Q3; an earlier change | decided |
| E14 | Budget continue and stop: the thread's owner or `chat.manage`; raise: `chat.manage` | `services/agents-service/src/ops_agents/api/chat_budget.py:109,200,207,219` | Owner continues, a team admin raises; both now through `can()`, with codes `not_owner` and `admin_only` | 2026-10-17 | an earlier change Q2, Q3 | decided |
| E15 | Team isolation and key refusals raised without a baseline code | `services/tools-service/src/ops_tools/modules/directory.py:103`; `send_policy_routes.py:54` | Team isolation (baseline); an API key holds no sending-policy cell (an earlier change Q2). The codes should be `team_forbidden` and `role_required` | 2026-10-17 | an earlier change Q3; an earlier change Q2 | decided; codes to fix |
| E16 | Gateway refusals from a record's settings: approval token (OPA), amount limit, egress allow list, model alias sensitivity and image clearance | `services/tools-service/src/ops_tools/app.py:456`; `limits.py:38`; `mailboxes.py:269,300`; `services/models-service/src/ops_models/app.py:650` | Each comes from data an admin or builder edits through `can()`: the operation, the egress list, the alias version | 2026-10-11 to 2026-10-17 | ADR-0005; an earlier change Q3; an earlier change Q3; AI gateway | decided |
| E17 | Store queries that read `members.role == "admin"`: the admin count shown per team, and re-mirroring Security admins when the Security team moves | `services/platform-service/src/ops_platform/store/teams.py:57`; `store/workspace.py:107` | Membership roles map to built-in assignments in the same transaction | 2026-10-17 | an earlier change Q1, Q3 | decided |
| E18 | An invite from an email domain outside the workspace's allowed domains is refused | `services/platform-service/src/ops_platform/teams.py:133` | `allowedDomains` is a sign-in policy setting; empty means any | 2026-10-16 | sign-in and sessions §4; shortcut audit | decided |
| E19 | The console decides by role name: the admin-only nav filter, and `useCanBuild` on the mock | `apps/console/src/components/app-sidebar.tsx:107`; `apps/console/src/hooks/me-queries.ts:47` | The behaviour is decided; the mechanism goes to `GET /v1/me/permissions` | 2026-10-18 | an earlier change | to fix |
| E20 | The Access table styles the admin badge by role name | `apps/console/src/components/access/members-panel.tsx:53` | Presentation only; decides nothing | | | consistent |
| E21 | `GET /v1/api-key-summaries` refused every person, workspace admins included | `services/platform-service/src/ops_platform/api/app.py` | Resolved 2026-10-19: a person with `can('access', 'manage')` in every team reads it; a service still needs `settings:view` (test_workspace_admin) | | | **resolved** |
| E22 | The console maps team roles to a session role `admin`, `member` or `viewer` | `apps/console/src/lib/auth/providers/platform.ts:70` | None. Sign-in Q6 is open (O06) | | | **no decision** |
| E23 | Every tool write waits for approval unless its operation says it runs at once; `open_case` runs at once | `services/tools-service/src/ops_tools/modules/seed.py:39`; `registry.py:22` | A write needs an approval token (ADR-0005); `open_case` without one is built (9411d062) but an earlier change Q1 is unanswered (O11) | 2026-10-17 | ADR-0005; an earlier change | decided for writes; open for `open_case` |
| E24 | Models-service admin routes take a service token only; no person reaches them | `services/models-service/src/ops_models/app.py` | A prototype shortcut until the Govern models page | 2026-10-16 | [identity and tenancy](identity-and-tenancy.md) shortcuts; an earlier change | to fix |
| E25 | Writes before a first publish: a draft test uses the draft, a live run needs the live version | `services/agents-service/src/ops_agents/api/auth.py:256-262` | A test run is a draft activity (`workflows.edit`); a live run is `workflows.run` | 2026-10-17 | an earlier change Q2 | decided |
| E26 | A team admin outside the Security team does not change egress, another team's secrets, storage settings or security reviews | `SECURITY_TEAM_ACTIONS` `catalogue.py:55` | These decide what every team may reach, so they are held in the Security team | 2026-10-17 | an earlier change Q1; an earlier change | decided |
| E27 | An admin edits only their own memory (`memory.edit` own) | `catalogue.py:135` | What agents remember about a person is that person's to correct or forget | 2026-10-17 | an earlier change | decided |
| E28 | API keys hold three fixed cells in code rather than a role | `KEY_GRANTS` `check.py:56` | A key is a bank system acting for one team: live runs, cancelling its own, and running the team's tools over MCP (reads only; a write waits for a person, `gateway_calls.py`) | 2026-10-19 | an earlier change Q1, Q2; an earlier change Q2; an earlier change Q4 | decided |
| E29 | `requesterMayDecide` is one value per workspace | `policies.py:48` (no `per_team`) | It is a team policy | 2026-10-18 | owner via orchestrator | to fix |
| E30 | A first SSO sign-in or an IdP group can give `chat_user`, `viewer`, `builder` or `approver`, never `admin` | `JIT_ROLES`, `services/platform-service/src/ops_platform/signin_settings.py:30` | None recorded; an earlier change names the default (Chat user) only | | an earlier change | **no decision** |
| E31 | No invite or role change sets the `chat_user` membership; only a first SSO sign-in does | `catalogue.py:165-167`; invite roles in `apps/console/src/components/access/roles.ts` | Owner 2026-10-18 asks that an admin can give someone Chat user; how is not decided (O10) | 2026-10-18 | an earlier change | **no decision** on the mechanism |
| E32 | Test threads need `agents.test`, which the code maps to `agents.edit`; no separate cell | `auth.py:239,256`; `services/agents-service/src/ops_agents/api/routers/chat.py:328` | Test threads are gated by `agents.test`, badged everywhere and kept out of counts and memory | 2026-10-18 | owner; an earlier change | decided; separate cell not built |
| E33 | Anyone holding `connections.manage` may create shared connections | `connections` in `AREAS` (`packages/ops_access/src/ops_access/catalogue.py`); `connection_rights`, `services/tools-service/src/ops_tools/connections/service.py`; grid migration `0025_connections_cells` | Decided: admins hold it by default; every member reads (`connections.view`) | 2026-10-19 | owner via orchestrator; an earlier change; an earlier change | built (1f1866c7) |
| E34 | `redactPii` masks what people see and defaults on; the model sees real values. AI steps follow the same decision through `aiStepsMaskPersonalData`, on unless a team sets false | `services/agents-service/src/ops_agents/api/agent_registry.py:39`; `packages/ops_access/src/ops_access/policies.py` (`aiStepsMaskPersonalData`, `team_off`) | Decided. an earlier change's card text ("masked in what the model sees") is superseded | 2026-10-19 | owner via orchestrator; an earlier change, an earlier change (approved by the orchestrator 2026-10-19) | an earlier change in review |
| E35 | A widget session approves for no team; the decision is made in Reviews | widget routes | Decided | 2026-10-17 | an earlier change Q3 | decided |
| E36 | Builder help and route by meaning have no policy yet; page images (`pageImages`) is uncommitted | `policies.py` | Off per team until turned on through `can()` | 2026-10-18 | owner; an earlier change; an earlier change | not built |
| E37 | Credentials are entered only by a person in the console; outside dev, start refuses a credential still set in the environment | tools secrets, platform sign-in settings | Root signing keys stay in the environment | 2026-10-18 | owner; an earlier change Q1, Q3 | decided |
| E38 | A seeded library widget answers 409 `seeded_widget` to an edit, whoever asks: it is locked by where it came from, not by a cell | `services/agents-service/src/ops_agents/api/routers/widgets.py:60` | A defect: seeded definitions are records editable through `can()`, never locked (owner's standing rule, 2026-10-18); the lock goes | 2026-10-19 | owner via orchestrator; an earlier change | to fix |
| E39 | Check before sending fails closed: a `checkBeforeSend` platform-service cannot read counts as on, and a judge that cannot answer holds the write for a person (`NO_JUDGE`), so an outage never lets a write skip its check | `services/tools-service/src/ops_tools/modules/policy.py` (`CheckBeforeSend.on`); `send_check.py` | Writes wait for a person while the policy or the judge is unreachable; nothing goes out unchecked | 2026-10-19 | an earlier change spec US4; the orchestrator tick 31 | decided |
| E40 | The MCP server refuses `/mcp/production/{team}` (403 `production_off`) for every team | `services/tools-service/src/ops_tools/mcp_server.py` | Production over MCP is a per-team setting, off by default (owner, an earlier change Q3); until that setting exists no team has it on | 2026-10-19 | an earlier change Q3; an earlier change | to fix (an earlier change turns it into the setting) |
| E41 | An API key is refused at a module's test console though it holds `tools.run` | `services/tools-service/src/ops_tools/modules/service.py` (`ModuleService.test`) | Keys hold `tools.run` for the gateway call path over MCP (E28), which logs and rate-limits each call; the test console is a person's and its reads are neither logged nor limited. Resolves once the test console's calls go through the logged, rate-limited gateway path (task on an earlier change) | 2026-10-19 | an earlier change Q4; an earlier change; the orchestrator | to fix |
| E42 | The workspace's owner cannot leave it, or be removed or demoted on the member routes, until they transfer it (409 `owner_must_transfer`) | `services/platform-service/src/ops_platform/workspace_lifecycle.py` (`leave`, `refuse_owner`) | A workspace always has one owner; ownership itself is the grid cell `workspace.manage` held by the built-in role Owner, moved only by a transfer | 2026-10-23 | owner via the orchestrator; an earlier change | decided |
| E43 | A team's last active admin cannot leave it (409 `last_admin`) | `services/platform-service/src/ops_platform/workspace_lifecycle.py` (`leave_team`) | A team never exists without an admin, as the member routes already keep for a removal or demotion | 2026-10-23 | owner via the orchestrator; an earlier change | decided |
| E44 | A closed workspace refuses sign-in, sessions and service tokens to everyone but its owner (403 `workspace_closed`), whatever their roles | `services/platform-service/src/ops_platform/auth.py` (`start_session`); `workspace_lifecycle.py` (`closed`) | A deleted workspace stays restorable by its owner for the restore window and is closed to everyone else; the maintainers reaches only `/v1/me`, sign-in and Restore | 2026-10-23 | owner via the orchestrator; an earlier change | decided |
| E45 | A plugin's tool module answers 403 `plugin_module` to every edit, publish, delete, review request and access request, whoever asks: its tools change only when the installed plugin is upgraded | `services/tools-service/src/ops_tools/modules/service.py` (`_not_a_plugin`) | The module is system-held, as the platform's tools are; teams turn the plugin on or off instead | 2026-10-29 | an earlier change review fix 6 | prototype |
| E46 | The `plugins` policy (the install switch) defaults to every plugin off, and a policy tools-service cannot read counts as off | `packages/ops_access/src/ops_access/policies.py`; `services/tools-service/src/ops_tools/plugins/switches.py` | No team sees a plugin until the platform admin (settings.manage in Security) turns it on; an outage never runs one the admin stopped | 2026-10-29 | an earlier change spec | prototype |
| E47 | A members-only hosted form refuses anyone signed in outside the team that shares it, and answers the same for a form that does not exist (403 `form_members_only`) | `services/agents-service/src/ops_agents/api/routers/forms.py` (`_member_form`) | The form is the team's own start form shared with its members; reading it in another team would cross the team boundary, so a person outside it learns nothing about it | 2026-10-30 | an earlier change spec (owner via the orchestrator) | prototype |

## Decided questions

Questions already put to the maintainers (or answered by the orchestrator for the maintainers) and answered. Cite the row id
when a question comes up again.

| # | Question | Answer | Date | Source |
|---|---|---|---|---|
| D01 | What do people call the stored `approver` role? | Reviewer. The stored and wire value stays `approver` until a migration renames it | 2026-10-17 | release plan; an earlier change Q6 (was this page's open question 1) |
| D02 | One role model per team, or capabilities per IdP group? | One role per team, built-in roles as data; the capability-role tabs were dropped | 2026-10-17 | an earlier change Q1 |
| D03 | Where does a role come from? | The verified token only (`access` claim for the `X-Team-Id` team), never a body, query or header the caller sets | 2026-10-17 | an earlier change Q6; an earlier change Q1 |
| D04 | Who writes definitions? | A builder or admin of the owning team; a reviewer decides; a viewer reads; refusals are 403 `role_required` | 2026-10-17 | an earlier change Q1 |
| D05 | How is another team's record refused? | 403 `team_forbidden` naming the owning team; another tenant's record is 404 | 2026-10-17 | an earlier change Q3; R5, R6 |
| D06 | Superseded 2026-10-22: every record belongs to one team ([identity and tenancy](identity-and-tenancy.md#the-team-is-the-workspace)). Was: who changes a record no team owns? | Whoever the grid lets change it in the acting team (replaces "an admin or whoever saved it") | 2026-10-18 | an earlier change Q2; a6a10c25 |
| D07 | Who pauses an agent? | A builder or admin, as for workflows | 2026-10-17 | an earlier change Q4 |
| D08 | Who starts a run? | A builder or admin, test and live; an API key of the team, live runs only | 2026-10-17 | an earlier change Q1; an earlier change Q2 |
| D09 | Who cancels a run? | Whoever started it, or a reviewer or admin of the run's team | 2026-10-17 | an earlier change Q2 |
| D10 | Who decides a review? | A reviewer or admin of the reviewing team, with separation of duties and step-up | 2026-10-17 | an earlier change Q3 |
| D11 | May viewers chat? | Yes: every role in the agent's team ("an agent no team owns is open to everyone" is superseded 2026-10-22: every agent belongs to one team) | 2026-10-17 | an earlier change Q4 (was this page's open question 3) |
| D12 | How does the console know whether to show Decide or Cancel? | From the server: `canDecide` and `canCancel` on each record, filled by `can()` | 2026-10-17 | an earlier change Q1, Q2 |
| D13 | Who may check another person's access, and does the check apply policies? | Whoever holds `access.view` in that team, a workspace admin for every team; the check runs the same `can()`, so policies show as reasons | 2026-10-17 | an earlier change Q1, Q2 |
| D14 | Is the checked person told? | No. Each check is audited with who checked whom | 2026-10-17 | an earlier change Q3 |
| D15 | Are defaults open? | Yes. Every policy starts open; stricter rules are settings an admin switches on | 2026-10-17 | an earlier change |
| D16 | Can admins do everything? | Yes, in their team; a workspace admin in every team | 2026-10-17 | owner; migration 0016; an earlier change |
| D17 | Is a refusal outside the grid and policies allowed? | No. It is a defect unless this page records the maintainers' decision | 2026-10-18 | owner; review checklist §3 |
| D18 | Are definitions code or records? | Database records seeded from files; built-in workflows, roles and task types are editable through `can()`, never locked | 2026-10-18 | owner; shortcut audit; an earlier change Q1 |
| D19 | Where does security for a definition live? | In the step that acts (`notDecidedBy`, `requesterMayDecide`), never in a lock on the definition | 2026-10-18 | owner |
| D20 | Is `requesterMayDecide` a rule or a setting? | A team policy, on by default | 2026-10-18 | owner; an earlier change (row E29) |
| D21 | Is separation of duties part of `can()`? | Yes, as `not_by` and `requested_by`; two-approver counting stays where approvals are counted | 2026-10-17 | an earlier change Q4 |
| D22 | How are roles shown to admins? | As a roles × permissions checkbox matrix; admins edit built-in roles' cells there | 2026-10-18 | owner via orchestrator; an earlier change |
| D23 | Is there a chat-only role? | Yes, Chat user: chats with the team's published agents, sees only its own threads | 2026-10-17 | owner; `catalogue.py:165` |
| D24 | What does a person see on a control they cannot use? | A ⓘ "why can't I" that names the missing cell or policy | 2026-10-18 | owner via orchestrator; an earlier change; an earlier change |
| D25 | Who is the test user? | Admin, builder and first seeded user are the same person for testing; role tests go through invites and role changes, with `OPS_SEED_EVERYONE_ADMIN` off | 2026-10-18 | owner; an earlier change |
| D26 | What role does an invite start on? | Viewer | 2026-10-18 | an earlier change (162a23c5) |
| D27 | Invite rules? | Seven days, single use, only a team admin invites, link shown once, no email until an earlier change | 2026-10-17 | an earlier change Q3; an earlier change |
| D28 | How are test threads gated? | `agents.test`, badged everywhere, kept out of counts, budgets and memory | 2026-10-18 | owner; an earlier change |
| D29 | Who creates shared connections? | Anyone holding `connections.manage` | 2026-10-19 | owner via orchestrator |
| D30 | Are AI features on by default? | No. Each is a team setting, off until turned on through `can()`: AI steps, task assist, check before sending, builder help, page images to the model | 2026-10-18 | owner; an earlier change to an earlier change Q3; an earlier change |
| D31 | What does `redactPii` mask? | What people see; it defaults on and the model sees real values | 2026-10-19 | owner via orchestrator |
| D32 | Who enters credentials? | Only a person, in the console. Root signing keys stay in the deployment's environment | 2026-10-18 | owner; an earlier change Q1 |
| D33 | Who adds every-team secrets that services read? | Superseded (2026-10-27): every tool secret belongs to a team and no service reads one; model provider keys move to an account-level store in models-service that account admins edit | 2026-10-18 | an earlier change Q2 |
| D34 | Who owns a team's secrets? | The team: its builders add, change and remove them, unless `securityTeamAddsSecrets` is on | 2026-10-17 | owner; `catalogue.py:104` |
| D35 | Is knowledge per person or per team? | Shared by the team: any builder changes or deletes its bases and sources | 2026-10-17 | owner; migration 0009 |
| D36 | Are chats private? | Yes by default (`chatThreadsOwnerOnly`); off lets the team's admins read them | 2026-10-17 | owner via orchestrator |
| D37 | Who edits what agents remember about a person? | That person only | 2026-10-17 | an earlier change |
| D38 | Where is a Security-team rule held? | In the Security team, a per-workspace setting; Admin elsewhere holds none of `SECURITY_TEAM_ACTIONS` | 2026-10-17 | an earlier change Q1; an earlier change |
| D39 | What does an assignment look like, and when does a change apply? | Person or team subject, a role, a team or `*`, an optional expiry; the permission version rises on every change and applies at the next token refresh | 2026-10-17 | an earlier change Q2, Q5 |
| D40 | Custom roles: when, how narrow, which cells? | Later; may be narrower than any built-in; may not hold secrets, egress or Security-team cells. The first answer is narrowed by D22 | 2026-10-17 | an earlier change Q1-Q3 |
| D41 | How does a service pass `can()`? | Its token lists `area:action` scopes; 403 `scope_required` otherwise | 2026-10-17 | an earlier change Q3 |
| D42 | Do people call service routes? | Yes: each with the cell it needs, answering their team's records only | 2026-10-18 | an earlier change Q1 |
| D43 | Who decides a module security review? | An approver or admin of the Security team for a security change, of the module's team otherwise; never the requester or saver | 2026-10-17 | an earlier change Q1; an earlier change Q1 |
| D44 | Who decides a tool access request, and who revokes a grant? | The module's team in Human Tasks, with the same requester policy and step-up; revoking stays with the module's builders and admins | 2026-10-17 | an earlier change Q1-Q3 |
| D45 | Which team owns a tools review run? | The deciding team; `created_by` is who asked, so the requester rule applies | 2026-10-18 | an earlier change Q1 |
| D46 | Which publishes wait for review? | Per team and area: always, major (default) or never; a security change is always reviewed by Security; an unreadable policy waits | 2026-10-17 | an earlier change Q1-Q3 |
| D47 | Who makes a widget deployment, and how does a person reach it? | A builder or admin of the agent's team; a 15-minute session from the bank's SSO token or a team key, bound to deployment, origin and person | 2026-10-17 | an earlier change Q1-Q4; an earlier change Q2 |
| D48 | May a widget session approve? | No; the decision is made in Reviews | 2026-10-17 | an earlier change Q3 |
| D49 | Who creates API keys, and how long do tokens live? | A team admin; tokens 15 minutes, sessions 8 hours; revocation reaches other services within 15 minutes | 2026-10-11 | an earlier change Q2, Q4, Q5 |
| D50 | Who continues or raises a spent chat budget? | The thread's owner continues; a team admin raises | 2026-10-17 | an earlier change Q2, Q3 |
| D51 | Who changes document types? | Whoever holds `files.create` in the team; others see the pages read only | 2026-10-18 | an earlier change Q1; an earlier change Q5; an earlier change Q2 |
| D52 | Who changes storage settings? | An admin of the Security team; every save audited | 2026-10-17 | an earlier change Q3 |
| D53 | Is a secret's team scope enforced in the console? | In the gateway: a call reads only its own team's secret, so another team's never reaches it (an earlier change replaced scopes with one team per secret); a secret in use cannot be deleted | 2026-10-17 | an earlier change Q4, Q5 |
| D54 | Who provisions a workspace, and what can a team change? | A platform admin or the command line; `system` records need `manage`, `managed` records are changed freely and template fields come back | 2026-10-17 | an earlier change Q2, Q3 |
| D55 | How are teams made? | Flat, created by a workspace admin; Security team and default team are settings | 2026-10-17 | an earlier change |
| D56 | Is the extraction floor an access rule? | No, a quality threshold with the engine's default | 2026-10-17 | owner via orchestrator |
| D57 | How does a password or SSO account step up? | Password plus TOTP when enrolled; SSO and Google at their IdP | 2026-10-16 | sign-in Q1, Q2 (commit 1b883aa) |
| D58 | Do money approvals need two people and a step-up? | Two distinct approvers when the operation says so, each with a step-up under five minutes old | 2026-10-11 | ADR-0005; sign-in 3.7 |

## Open questions

Still waiting for the maintainers. A recommendation is not an answer; nothing here may be quoted as decided.

| # | Question | Raised | Where it bites |
|---|---|---|---|
| O01 | Which platform roles exist (model risk, Security, platform, auditor), and are they teams with roles or tenant-wide roles? | this page, Q4 | Models admin (E24), auditors outside a team |
| O02 | May a 403 name the owning team when the data gateway hides that the record exists? | this page, Q5 | Data gateway |
| O03 | Must API keys expire, and with what maximum? | this page, Q7 | Key creation |
| O04 | Should a step-up bind to what it approves (review ids, amounts)? | sign-in Q3 | Bulk money approvals |
| O05 | Does turning MFA off, self-signup on, or removing the last verified domain need a second admin? | sign-in Q5 | Sign-in settings |
| O06 | Does the session keep a workspace role (`admin`, `member`, `viewer`), or only teams? | sign-in Q6 | E22 |
| O07 | Once built-in cells are editable (D22), may an admin tick secrets, egress or Security-team cells on them? D40 forbids it for custom roles | an earlier change Q3 against D22 | an earlier change |
| O08 | Do admin and Security roles expire and need a second admin to grant, in v1? | an earlier change | Access requests |
| O09 | May a first SSO sign-in or an IdP group give Admin? | E30 | `signin_settings.py:30` |
| O10 | How does an admin give someone Chat user: an invite role, a role change, or a grant? | E31 | an earlier change |
| O11 | May an agent open a case without approval, and do test runs open real cases? | an earlier change Q1, Q2 (unanswered; built that way) | E23 |
| O12 | Should a person with a cell read every team's API key summaries? | E21 | `app.py:699` |
| O13 | Should tools-service's bulk delete skip system modules for admins? | E05 | `modules/service.py:1109` |

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
| Access check | Each architecture review, and each builder question about access | A card, interview question or diff conflicts with this page, or asks something [Decided questions](#decided-questions) answers |

A new decision adds a row to Decided questions in the same change that acts on it; a new exception adds a register
row and an allowlist line with a `Standards-exception:` trailer.
