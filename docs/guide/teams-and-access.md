# Teams and access

Status: current. Rows marked planned are designed and not built.

When several teams share one workspace, you need to decide who sees which work and who may change it. This page shows
how to draw a data boundary around each team and give each person only the actions their job needs.

## Why each team needs its own space

A card team and a lending team should not read each other's cases. A new joiner should be able to chat with an agent
before they are allowed to change one, and a claims team may want a reviewer to decide a settlement without being able
to edit the agent that proposed it. When everyone in the workspace can open everything, your risk review has no basis
for approving the rollout. When access is arranged by hand for each person, it falls out of date the first time
someone changes jobs.

Ops AI groups people into teams and gives each person one or more roles in each team they belong to. You use teams to
draw the data boundary, and roles to decide what each person may do inside it.

## Setting up teams and roles

<!-- site: steps -->
1. **Make a team for each group that must be kept separate.** The team owns its agents, workflows, knowledge, files and
   cases.
2. **Invite people.** Every invited person starts as a Viewer, who can read the team's work and chat with its agents.
3. **Give each person the role their job needs.** Roles are given per team, and a role can carry an expiry date.
4. **Check the grid.** The **Roles** grid shows which actions each role may take. If a role needs more or less, your
   admin changes the cell.

## Try it from the command line

These commands show who you are, the roles in your team and what one of them may do. The last one invites a new
person as a Viewer.

```bash
opsai people me
opsai people roles
opsai people role builder
opsai people invite a.osei@example.com --role viewer
```

On its own, `invite` prints the invite without sending anything, so you can check it first. Add `--send` when you
want it delivered. In the console you find the same views under **Govern › Access**, which holds the members, the
teams, the **Roles** grid and **Tool access**.

## What a team's boundary covers

A team owns its agents, workflows, knowledge, files and cases, together with the work they produce.

```mermaid caption="The data boundary: your organisation holds teams, each team owns its work, and a person reaches it through a role in that team"
flowchart TD
  O[Your organisation] --> T[A team]
  P[A person] -->|Role in that team| T
  T --> W[Its work and records]
```

When several organisations share the same install, records of another organisation are never found from yours. Inside your organisation, someone outside a team cannot open that team's records, even
with a direct link. The server refuses the request and names the team that owns the record, so the person knows whom
to ask.

- A person holds roles per team and may hold different roles in different teams. Someone given the Admin role in every
  team becomes a workspace admin. A role can be given with an expiry date.
- What you may do in a team is the sum of your roles there. Each permission pairs an area (agents, workflows, cases,
  knowledge, ...) with an action (view, create, edit, publish, delete, run, decide, manage), and covers either every
  record in the team or only your own.
- The server checks access on every request. When an admin changes someone's roles, the change applies on that
  person's next request, so they do not need to sign out.

## The roles every team starts with

| Role | What it may do |
|---|---|
| Admin | Everything in the team |
| Builder | Build and run agents, workflows, tools, knowledge, connections and secrets; not manage people or roles |
| Reviewer | Read the team's work and decide its reviews and Human Tasks |
| Viewer | Read the team's work and chat with its agents. Every invite starts here |
| Chat user | Chat with the team's published agents and read only their own chats. Given on a first single sign-on |
| Security admin | Egress, any team's secrets, storage settings and security reviews of tool modules. Held by admins of the Security team |
| Owner | Transfers, closes and restores the workspace. One person holds it, and only a transfer moves it |

A workflow's schedule follows the same cells in the grid. Anyone who may view the workflow can read its schedule. To
save or clear the schedule, a person needs the right to edit the workflow and to add deployments in its team. To resume
a paused workflow, they need the right to edit it. A Viewer or Chat user sees the schedule but no buttons to change it
([Schedule a workflow or an agent](schedule-a-workflow.md)).

## Settings you can change

| Setting | Where | What it does | Default |
|---|---|---|---|
| A cell in the roles grid | Govern › Access › Roles | Allows or refuses one action of one role, for all records or your own | As in the table above |
| Team policies | Govern › Policies | Stricter rules a team switches on, such as step-up before decisions | Off |
| Approvals | Settings › Approvals | Which writes wait for a person ([Human tasks and approvals](human-tasks.md)) | Off |
| Sign-in | Settings | Single sign-on over OIDC or SAML, chosen by verified email domain, or password | Password |

## What is not built yet

- Custom roles are planned. Until they arrive, you change what the Builder, Reviewer, Viewer and Chat user roles may
  do by editing their cells in the grid. The Admin, Security admin and Owner roles are fixed.
- Every service keeps teams and organisations apart. The database itself enforces that separation only in part: it
  covers files, documents, agents and platform data today, and the rest is planned.
- Admins can do everything in their own team, but a few security actions still need someone from the Security team.

## How you know it is working

A newly invited person starts as a Viewer and can read the team's work and chat with its agents. Records of another
organisation on the same install are never found. When someone outside a team opens one of its records by direct link,
the server refuses and names the team that owns it. A change to a person's roles applies on their next request,
without signing out. When your risk review asks who may do what, the roles grid answers it on one page.

## What happens without teams and roles

Without teams, every person sees every team's work, and the rollout waits on a risk review that has no grounds to sign
off. Without roles, access is arranged person by person, so when someone leaves they keep whatever the last admin
forgot to remove.

## Next

<!-- site: cards -->
- **[Human tasks and approvals](human-tasks.md)**: who decides, and when a person must.
- **[Security](../security/README.md)**: sign-in, isolation and audit for a security review.
- **[Tools and apps](apps.md)**: whose account a tool uses when it runs.
