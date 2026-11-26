# Teams and access

Status: current. Rows marked planned are designed and not built.

**Draw the data boundary around each team, and give each person only the actions their job needs.**

## Two teams should not read each other's work

A card team and a lending team should not read each other's cases, and a new joiner should be able to chat with an agent
before they can change one. A claims team may let a reviewer decide a settlement but not edit the agent that proposed it.
If everyone in the workspace can open everything, a risk review cannot approve the rollout. If access is arranged by
hand for each person, it drifts the first time someone changes jobs.

Ops AI groups people into teams, and gives each person roles in each team they belong to. Use teams to draw the data
boundary, and roles to decide what each person may do inside it.

## The plan

<!-- site: steps -->
1. **Make a team for each group that must be separate.** The team owns its agents, workflows, knowledge, files and
   cases.
2. **Invite people.** Every invite starts as a Viewer, who can read and chat.
3. **Give each person the role the job needs.** Roles are per team, and can carry an expiry date.
4. **Check the grid.** The **Roles** grid shows which action each role may take. Change a cell if a role needs more or
   less.

## Try it

See the roles in your team and what one of them may do, then invite someone.

```bash
opsai people me
opsai people roles
opsai people role builder
opsai people invite a.osei@example.com --role viewer
```

`invite` prints the invite and sends nothing; add `--send` to send it. In the console the same views are under
**Govern › Access**: members, teams, the **Roles** grid and **Tool access**.

## What the boundary covers

- A team owns its agents, workflows, knowledge, files and cases, and the work they produce. Someone outside the team
  cannot open them, even with a direct link: the server refuses and names the team that owns the record.
- Your organisation is the outer boundary. Records of another organisation on the same install are never found.
- A person holds roles per team, and may hold different roles in different teams. The Admin role given in every team makes
  that person a workspace admin. A role can be given with an expiry date.
- What you may do is the sum of your roles in that team. Each permission is an area (agents, workflows, cases,
  knowledge, ...) and an action (view, create, edit, publish, delete, run, decide, manage), for every record in the team
  or only your own.
- Access is checked on the server for every request. A change to someone's roles applies on their next request, without
  signing out.

## Built-in roles

| Role | What it may do |
|---|---|
| Admin | Everything in the team |
| Builder | Build and run agents, workflows, tools, knowledge, connections and secrets; not manage people or roles |
| Reviewer | Read the team's work and decide its reviews and Human Tasks |
| Viewer | Read the team's work and chat with its agents. Every invite starts here |
| Chat user | Chat with the team's published agents and read only their own chats. Given on a first single sign-on |
| Security admin | Egress, any team's secrets, storage settings and security reviews of tool modules. Held by admins of the Security team |
| Owner | Transfers, closes and restores the workspace. One person holds it, and only a transfer moves it |

## Options

| Setting | Where | What it does | Default |
|---|---|---|---|
| A cell in the roles grid | Govern › Access › Roles | Allows or refuses one action of one role, for all records or your own | As in the table above |
| Team policies | Govern › Policies | Stricter rules a team switches on, such as step-up before decisions | Off |
| Approvals | Settings › Approvals | Which writes wait for a person ([Human tasks and approvals](human-tasks.md)) | Off |
| Sign-in | Settings | Single sign-on over OIDC or SAML, chosen by verified email domain, or password | Password |

## Limits

- Custom roles are planned. Today you change what the Builder, Reviewer, Viewer and Chat user roles may do in the grid.
  Admin, Security admin and Owner are fixed.
- Team and organisation separation is enforced in every service. Enforcement in the database itself as well is partial:
  files, documents, agents and platform data today, the rest planned.
- Admins can do everything in their team. A few security actions still need the Security team.

## What success looks like

An invited person starts as a Viewer and can read and chat. Someone outside a team who opens a record by direct link is
refused, and the refusal names the team that owns it. A change to a person's roles applies on their next request,
without signing out. A risk review reads the roles grid and the answer is on one page.

## What skipping it costs

Without teams, every person sees every team's work, and the rollout waits on a risk review that cannot sign off.
Without roles, access is arranged person by person and a leaver keeps what the last admin forgot to remove.

## Next

<!-- site: cards -->
- **[Human tasks and approvals](human-tasks.md)**: who decides, and when a person must.
- **[Security](../security/README.md)**: sign-in, isolation and audit for a security review.
- **[Tools and apps](apps.md)**: whose account a tool uses when it runs.
