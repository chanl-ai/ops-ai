# Glossary

Every page in these docs uses one name for each thing, and the name is the one the console shows. Use this page to
look up a word, or to find where something lives in the console.

A console path reads left to right: the sidebar section, the row, then a tab on that page when there is one. **New chat**
sits above the sections.
Settings has its own sidebar, which opens from **Governance › Settings**.

## What you work with

| Name | What it is | In the console | Not |
|---|---|---|---|
| Chat | A conversation between a person and an agent | New chat | |
| Case | The record of one piece of work: its subject, what it waits on, its history | Work › Cases | |
| Human task | A request for a person to decide something before work continues | Work › Human Tasks | HITL |
| Team | A group of people that owns agents, workflows, knowledge and cases | Settings › Team › General | |

## What you build

| Name | What it is | In the console | Not |
|---|---|---|---|
| Agent | A model with instructions, tools, knowledge, skills and guardrails | Agent Builder › Agents | |
| Workflow | A versioned set of steps: triggers, AI steps, human tasks, tool calls | Agent Builder › Workflows | |
| Run | One piece of work by a workflow, with a status and a result | Agent Builder › Workflows › Runs | |
| Channel | A place work arrives from, such as a mailbox a workflow watches | Agent Builder › Channels | |
| Skill | Reusable instructions an agent follows for one kind of job | Agent Builder › Skills | |
| Guardrail | A rule that restricts an agent; it never widens access | Agent Builder › Guardrails | |
| Widget | A display block an agent can show in a chat | Agent Builder › Widgets | |

## What agents reach

| Name | What it is | In the console | Not |
|---|---|---|---|
| App | A system an agent can act in, such as Salesforce or GitHub | Data Gateway › Apps | connector |
| My apps | Your own sign-ins to the team's apps | Work › My apps | |
| Auth config | How an app signs in: OAuth, a key or a certificate | Data Gateway › Apps | |
| Tool | One operation on one app, marked read or write | Data Gateway › Tools | |
| Knowledge base | Documents an agent searches to answer | Data Gateway › Knowledge | KB, Brain |
| Secret | A value a tool sends, such as an API key; encrypted, never shown again | Data Gateway › Secrets | |
| File | Any file the workspace stores | Data Gateway › Files | |
| Document type | One kind of document, with its fields and checks | Data Gateway › Document types | |

## How you keep control

| Name | What it is | In the console | Not |
|---|---|---|---|
| Activity | Everything that happened in the team: runs, chats, emails and decisions | Governance › Activity | |
| Tool call | One use of a tool, with who called it and the result | Governance › Activity › Tool calls | |
| Audit log | Sign-ins, role changes, key changes and policy changes | Governance › Activity › Audit log | |
| Review | A decision a person made, or still owes, on any team | Governance › Reviews | |
| Member | A person in a team | Governance › Access | |
| Role | The set of things a member may do | Governance › Access › Roles | |
| Tool access | Which workflows may call which tools, and until when | Governance › Access › Tool access | |
| Policy | A workspace rule on who decides what, and how long it may wait | Governance › Policies | |
| Eval | A test suite for an agent | Governance › Evals | |
| Model inventory | Every agent and workflow with its risk tier and findings | Governance › Evals › Model inventory | |

## Settings

| Name | What it is | In the console | Not |
|---|---|---|---|
| Settings | The settings of the workspace and of each team | Governance › Settings | |
| Model provider | A key your AI models sign in with | Settings › Workspace › Model providers | |
| Storage | Where files are kept, with upload limits and retention | Settings › Workspace › Storage | |
| Usage and cost | Tokens, model cost and tool calls | Settings › Workspace › Usage and cost | |
| Notifications | Where approvals and alerts go | Settings › Team › Notifications | |
| Webhook | An event sent to one of your other systems | Settings › Team › Webhooks | |
| API key | A key for a system that starts runs or reads logs | Settings › Team › API keys | |
| Approvals | Whether agents ask before they change an app, and who answers | Settings › Govern › Policies › Approvals | |
| Sign-in | Sign-in methods, single sign-on and sessions | Settings › Govern › Security › Sign-in | |
| Egress | The hosts a tool call may reach | Settings › Govern › Security › Egress | |
