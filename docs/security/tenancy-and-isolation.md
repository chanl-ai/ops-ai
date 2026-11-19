# Tenancy and isolation

Status: current. Checked against the release's access, storage and database rules.

A bank runs many teams on one Ops AI: card disputes, lending, branch operations. Each team's agents, workflows,
knowledge, files, chats and cases must stay inside that team, and one organisation's data must never reach another's.
This page says where those walls are, who can see across them, and where a wall is still enforced in one layer only.

## Try it

Sign in as a member of one team and open a record that belongs to another team, by pasting its link.

<!-- site: steps -->
1. In the console, open a case in the Disputes team and copy its address.
2. Sign in as someone who belongs only to the Lending team.
3. Paste the address. The console answers that the case was not found.

The server answers "not found" rather than "forbidden", so a person outside the team cannot learn that the record
exists.

## How it works

| Boundary | Behaviour |
|---|---|
| Organisation (tenant) | Taken from the verified sign-in token or API key on every request, never from a field the caller sends. A record of another organisation answers "not found" |
| Team | Every read of a team's records is filtered to the teams the person belongs to. Roles decide what a person may do inside a team; no role opens another team's data |
| Chats | A chat thread is read only by the person who started it, unless the team turns that off; then the team's admins read it too |
| Files | Two teams that upload the same file each keep their own copy of what was read from it, and neither sees the other's |
| Background work | Timers and queued work are picked up by a system process, then run under the organisation and team of the record they belong to. No request runs with that process's reach |
| Service to service | Each service signs its calls with its own key, and a service accepts only the calls that caller is allowed to make |

The database adds a second wall under the service checks. For the agents and platform data, every table holding
customer data enforces row-level security by organisation: a session that has not named its organisation sees no
rows, and the rule applies to the table owner too. Each service connects with its own database login that can read and
write only its own tables.

## Options

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Private chat threads | Each chat is read only by the person who started it. Off: the team's admins read the team's chats too | On | A Security admin, in Governance › Policies |
| Team membership | Which teams a person belongs to, and their role in each | Set by invite, or by sign-in group rules ([Identity and sign-in](identity-and-sign-in.md)) | A team admin, in Settings › Members |
| One organisation or several per installation | A self-hosted install usually holds one organisation; a hosted install holds several | Per installation | The operator, at install |

## Limits

- Database row-level security covers the agents and platform data today. For tools, models, knowledge, files and
  documents the organisation filter is in the service code; database rules for a connection's saved sign-ins, and
  team-level rules for files and documents, are built. The rest is planned.
- Model aliases, provider connections and model keys belong to the installation, so every organisation on one
  installation shares them. A hosted installation that needs separate model accounts per organisation runs separate
  installations.
- Custom roles are planned; today a person holds one of the built-in roles in each team.

## Next

<!-- site: cards -->
- **[Identity and sign-in](identity-and-sign-in.md)**: How people prove who they are, and how sign-in groups put them in teams.
- **[Access, approvals and audit](access-approvals-and-audit.md)**: What each role may do, which writes wait for a person, and what is recorded.
- **[Data handling and masking](data-handling-and-masking.md)**: What is stored, for how long, and what people see masked.
