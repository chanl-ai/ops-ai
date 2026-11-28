# Tenancy and isolation

Status: current.

A bank runs many teams on one Ops AI: card disputes, lending, branch operations. Each team's agents, workflows, knowledge, files, chats and cases belong to that team alone. If your installation holds more than one organisation, one organisation's data must also stay out of reach of another's. A security reviewer will ask where those walls are, who can see across them, and what still stands if one layer has a bug.

This page shows you how to check the wall yourself, and then lists each layer that holds it.

## Check the wall from the other side

Sign in as a member of one team and open a record that belongs to another team, by pasting its link.

<!-- site: steps -->
1. In the console, open a case in the Disputes team and copy its address.
2. Sign in as someone who belongs only to the Lending team.
3. Paste the address. The console answers that the case was not found.

The server answers "not found" and never "forbidden". A person outside the team cannot learn that the record exists, and its identifier reveals nothing. The same holds for agents, workflows, runs, files, knowledge bases and every other team record.

## What success looks like

Lending sees only lending records in every list, count and search. A person who belongs to both teams sees one team at a time, because every request acts in the team they have selected, and switching team changes everything on the screen. Nothing is shared between teams except what you install as a separate copy from the catalogue, which belongs to the team that installed it from then on.

## What skipping it would cost

With only a filter in the application code, one missed filter in one new screen shows another team's cases. Ops AI repeats the check in the database, so a bug in a service still cannot return rows the caller is not entitled to.

## How a request is kept inside its team

<!-- site: sequence caption="One request from the console to the database, and where the organisation and the team come from" -->
1. **Person → Console**: Opens a page in the team they have selected
2. **Console → Service**: Sends the request with the person's signed token and the selected team
   - The organisation comes from the verified token or API key, never from a field the caller sends. The team is checked against the person's memberships.
3. **Service → Database**: Reads or writes for that organisation and team
   - The service names the organisation and team to the database for the length of the transaction.
4. **Database → Service**: Returns only the rows that organisation and team own
   - A session that has not named its organisation sees no rows, and the rule applies to the table owner too.
5. **Service → Console**: Answers
   - A record of another team or organisation answers "not found".

## The layers

| Boundary | Behaviour |
|---|---|
| Organisation | Taken from the verified sign-in token or API key on every request. A record of another organisation answers "not found" |
| Team | Every request acts in one team the person belongs to. Roles decide what a person may do inside a team, and no role opens another team's data |
| Chats | A chat thread is read only by the person who started it, unless a Security admin turns that off. Then the team's admins read the team's chats too |
| Files | Two teams that upload the same file each keep their own copy of it and of what was read from it, and neither sees the other's |
| Background work | Timers and queued work are picked up by a system process, which then does the work under the organisation and team of the record it belongs to. No request ever runs with the system process's reach |
| Service to service | Each service signs its calls with its own key, and a service accepts only the calls that its caller is allowed to make |
| Database | Row-level security by organisation, forced on the tables that hold an organisation's records, on PostgreSQL and SQL Server. Most tables that belong to a team are also held to the acting team. Each service connects with its own database login, which can read and write only its own tables |
| Security team | A few actions reach across teams, such as the egress allow-list, storage settings and tool security reviews. They need a role in the workspace's Security team, and a role in any other team grants none of them |

## Settings

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Private chat threads | Each chat is read only by the person who started it. Off: the team's admins read the team's chats too | On | A Security admin, in Govern › Policies |
| Team membership | Which teams a person belongs to, and their role in each | Set by invitation or by sign-in group rules ([Identity and sign-in](identity-and-sign-in.md)) | A team admin, in Govern › Access |
| One organisation or several per installation | A self-hosted install holds one organisation, and a hosted install can hold several | One | The operator, at install |

## What is not built yet

- Model aliases belong to the installation, so every team on it shares them. Provider keys, model keys and the call log belong to one organisation each.
- The database rules do not apply to whoever administers the database. A person with database owner access can read every row, so keep that access to the few people who need it.

## Next

<!-- site: cards -->
- **[Identity and sign-in](identity-and-sign-in.md)**: How people prove who they are, and how sign-in groups put them in teams.
- **[Access, approvals and audit](access-approvals-and-audit.md)**: What each role may do, which writes wait for a person, and what is recorded.
- **[Data handling and masking](data-handling-and-masking.md)**: What is stored, for how long, and what people see masked.
