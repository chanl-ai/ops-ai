# A viewer sees the team's records read-only

Status: current. Id: `uc-099`. Service: `console`. Layers: api, ui. Cards: c-109 (console), c-115 (services).

A viewer reads the team's agents, workflows, skills, guardrails, widgets, tools and knowledge bases but cannot change them. The
console reads what `can()` grants each person on the team from platform-service (`GET /v1/me/permissions`, c-186) and
shows create, edit, publish, pause and delete only to someone it lets edit the team's records; a viewer sees the same pages with record forms disabled and a "View only"
notice. agents-service and kb-service refuse the same writes from a viewer or reviewer with 403 `role_required`
(c-115), so an API caller meets the rule the console shows. Design: [roles and permissions](../platform-service/roles-and-permissions.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Ravi Menon, viewer on team_ops, and James Richardson, builder on team_ops | platform-service dev seed (`services/platform-service/seed/people.json`) |

Each script starts its own stack with platform sign-in; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Ravi opens Agents, Workflows, Skills, Guardrails, Widgets, Tools and Knowledge bases | No create button on any of them |
| 2 | Ravi opens an agent | A "View only" notice naming the roles that edit agents and who holds them (James Richardson); no Save or More actions; the Name field is disabled |
| 2b | Ravi opens the dispute_email workflow | A "View only" notice; no Publish or More actions (the page reads the workflow's own `canEdit`, `canDelete`, `canPublish`) |
| 3 | James opens the same pages, agent and workflow | Every create button; Save shows, no notice, Name editable; the workflow's More actions shows |
| 4 | Both sign-ins | The console asked `GET /v1/me/permissions` what each person may do |
| 5 | James creates an agent, workflow, workflow definition, guardrail, skill, knowledge base and source through the services | Each answers 2xx (setup; any other status stops the run) |
| 6 | Ravi, then Maya (reviewer), send the 20 writes the builder pages send (create, edit, publish, pause, delete) straight to agents-service and kb-service | Every one answers 403 `role_required` |
| 7 | James edits the agent, workflow draft, guardrail and knowledge base | Each answers 200 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-099-api.py` (steps 5-7) | passing |
| ui | `console/scripts/test-uc-099-ui.mjs` (steps 1-4, 2b) | passing |

## Non-vacuous check

Step 3 is the control in the same run: the buttons step 1 counts absent are present for a builder. Making
`useCanBuild` (`apps/console/src/hooks/me-queries.ts`) return true for every role fails step 1. Step 7 is the api
layer's control: the same bodies pass for a builder. Before c-115 the services took every write in step 6 from a viewer
(quality-loop tick 7, A1), and with the role rule removed the c-115 suites fail on every route.
