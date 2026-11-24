# Teams and access

Status: current. Rows marked planned are designed and not built.

A card team and a lending team should not read each other's cases, and a new joiner should be able to chat with an
agent before they can change one. Ops AI groups people into teams, and gives each person roles in each team they belong
to. Use teams to draw the data boundary, and roles to decide what each person may do inside it.

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

## How it works

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

From 1.2.0 only an Admin may approve their own request. To let another role's holders approve their own, tick
**Approve own requests** on that role in Govern › Access › Roles. Each tick and untick is in the audit log.

## Options

| Setting | Where | What it does | Default |
|---|---|---|---|
| A cell in the roles grid | Govern › Access › Roles | Allows or refuses one action of one role, for all records or your own | As in the table above |
| Team policies | Govern › Policies | Stricter rules a team switches on, such as step-up before decisions | Off |
| Approvals | Settings › Approvals | Which writes wait for a person ([Human tasks and approvals](human-tasks.md)) | Off |
| Sign-in | Settings | Single sign-on over OIDC or SAML, chosen by verified email domain, or password | Password |

## Limits

- Custom roles are planned. Today you change what the built-in roles may do in the grid.
- Team and organisation separation is enforced in every service. Enforcement in the database itself as well is partial:
  files, documents, agents and platform data today, the rest planned.
- Admins can do everything in their team. A few security actions still need the Security team.

## Next

<!-- site: cards -->
- **[Human tasks and approvals](human-tasks.md)**: who decides, and when a person must.
- **[Security](../security/README.md)**: sign-in, isolation and audit for a security review.
- **[Tools and apps](apps.md)**: whose account a tool uses when it runs.
