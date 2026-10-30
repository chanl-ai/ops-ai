# Admins see roles, a person's effective access and why an action is refused

Status: current. Id: `uc-267`. Service: `console`. Layers: ui. Card: an earlier change.

An admin answers access questions on screen: what a role allows, what a person can do and which role grants it, and
(later steps) whether one action is allowed and why a button is locked.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and the dev seed | The use-case stack seeds itself: Wanjiru Kamau admin of Platform and Admin in every team (a workspace admin) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru opens Access › Roles, then Viewer | Every role with its permissions and holders; Viewer opens read-only (Built in), with View on Agents and no Edit, and no edit control |
| 2 | She reads her own row on Members | Admin, and "Admin · every team" beside it |
| 3 | She opens her row | Her page lists In every team (from Admin) and In Platform (from Admin) |
| 4 | In Operations she opens Maya Okafor, checks Reviews › Decide asked for by Maya; the workspace then turns Requester may decide off and she checks again | Allowed, granted by Reviewer; then Not allowed: "You asked for this, so someone else has to decide it." |
| 5 | James drafts an agent; Maya Okafor, a Reviewer, opens it and hovers the ⓘ beside Request publish | The button is disabled; the ⓘ says it needs Publish on Agents, which roles grant it, and who to ask |
| 6 | James saves a workflow draft; Maya opens it and focuses the ⓘ beside Publish | Publish is disabled, not missing; the ⓘ says it needs Publish on Workflows and who to ask |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-267-ui.mjs` | passing |
