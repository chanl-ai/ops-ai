# Agents use cases

Status: current (design, 2026-11-12). Every use case about an agent: making, publishing and testing one, what it may
call, what stops it, what it remembers, what a team starts from, with what each proves and where the SDK, CLI, MCP and
console layers stand. Workflows, mailboxes and Human Tasks have their own area lists.

Each page is written as: a short task title; "In this example we will do X. It assumes Y and Z."; numbered steps through
the SDK, the CLI or the console, using the shared steps in the use cases README. The SDK is the main connecting point: a
console step is only written once the same step exists through the SDK. A step the SDK or the command line cannot do
is an open row in the page's Gaps table, not a call to the service's own address.

## The list

States come from the registry and runs. "page" means the page runs on `make usecase-test UC=<id> LAYER=sdk|cli`.

| Id | Short title | What it proves | Layers | State |
|---|---|---|---|---|
| uc-086 | An agent with three tools | A bank API imported, reviewed and published reaches an agent; a read answers, a write is held until a second person approves | api, sdk, cli, ui | ui 16 of 16 pass; sdk and cli have no page yet |
| uc-018 | Make, publish and chat with an agent | A builder drafts, edits and publishes an agent and chats with it | api, sdk, cli, ui | api, ui pass; no page |
| uc-740 | Start a skill from a template | A team lists templates of each kind and installs a starter skill as its own copy | sdk, cli | page |
| uc-741 | List and install templates from an assistant | An assistant on the team address lists templates and installs one as the person it signed in as | mcp | page |
| uc-742 | A team's skill is an assistant's prompt | An installed skill is offered as a prompt with its inputs as arguments | mcp | page |
| uc-590 | Install a pack's agent, skill, workflow and document type | Each copy goes through the checks a person's create goes through | api, sdk, cli, ui | passing; no page |
| uc-085 | Block a topic with a guardrail | An agent refuses before answering, through the guardrail version it pins; a streamed answer is replaced when its check fails | api, sdk, ui | api, ui pass |
| uc-049 | A write waits for the people its policy names | The write runs only after that many approve; a builder cannot approve their own | api, ui | passing |
| uc-088 | Set the limits callers may override | A builder publishes limits with the agent and a chat shows when its budget is spent | ui | passing |
| uc-247 | Test an agent before it is live | A test turn on a real thread the server marks test, in the page's right panel, showing knowledge cited, tools called and where it would pause | api, ui | passing |
| uc-135 | An agent remembers each person | A person sees, corrects, exports and forgets what an agent keeps, and it follows them across the team's agents | api, ui | api, ui pass |
| uc-128 | The team's default agent asks specialists | Chat starts on the default agent; @ hands the chat over and back | api, ui | passing |
| uc-130 | Embed an agent | The Channels tab shows the embed, its sites, keys and usage; an embed retires for good | api, ui | passing |
| uc-265 | Personal data is masked | Replies, stored messages and workflow output show masked data | api, ui | not run |
| uc-621 | A builder runs the foundation Examples | The five example agents and workflows run through the SDK | sdk | not run |
| uc-028 | An agent runs on its publisher's model | The model alias the publisher chose is the one used | api | passing |

## Merged, dropped, moved

| Change | Why |
|---|---|
| uc-048 and uc-610 fold into uc-086 as its api layer | Grant, call and find-by-search are the same path uc-086 walks; their scripts stay as its api checks |
| uc-104 and uc-229 fold into uc-085 | A pinned guardrail version and a replaced stream are two steps of the guardrail story. uc-731 (name taken) stays an api script |
| uc-133 and uc-253 fold into uc-247 | A test reply's steps and the page's panel are two views of one test turn |
| uc-134 and uc-561 fold into uc-135 as its api layer | Memory read and forgotten through the API is the first half of what a person does in the chat |
| uc-136 folds into uc-130 | Embed snippets are step 3 of the Channels tab |
| uc-622 and uc-624 fold into uc-621 | One page runs all the Examples; the three composition checks are steps |
| uc-109, uc-117, uc-119 move to the Chat area list | They are the chat widget on another site, not the agent |
| uc-619, uc-696, uc-697, uc-704 move to the Knowledge and Tools lists | A new team's knowledge, and the account an agent names, are not agent behaviour |
| uc-100, uc-140 stay failing and are not agent pages | Console plan checks and the shared demo walk; they are owned by the console list |

## What the layers need

| Layer | Needs |
|---|---|
| sdk, cli | `lib/page_stack.py` starts the stack the page's Details row names. An agents page uses the templates stack (platform-service, tools-service with the starters pack and the team MCP address, agents-service) so a page starts one stack and not three |
| mcp | One MCP tab, run by the official Python MCP client the way Claude or Cursor connects; the stack does the company sign-in and hands the token over. No TypeScript or CLI tab is expected |
| ui | Scripts on `/build/agents` with a screenshot at 1440 and 390 and a clip under 15 s and 2 MB (`OPS_USECASE_MEDIA=1`) |
