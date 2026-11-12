# Use cases

Status: draft for review. Each use case is one thing a person does with Ops AI, told as a short story with numbered
steps. The code under each step is the test: the same Python, TypeScript and command-line code runs on every release,
so a step on this site is a step that passed.

## How to read one

| Part | What it tells you |
|---|---|
| Who is in it | The people in the story, their roles, and the profile each one signs in with |
| Before you start | The few lines that connect to Ops AI; the same lines connect to your own deployment |
| Steps | One heading per step, the code in three tabs, and the result expected in plain words |
| What proves it | The step that fails when the behaviour breaks |
| In the console | The same story clicked through the screens, where there is one |

## Run them

| Task | Command |
|---|---|
| One use case, every tab | `make usecase-test UC=uc-676` |
| One tab | `make usecase-test UC=uc-676 LAYER=sdk` runs Python and TypeScript; `LAYER=cli` runs the command line |
| The code of one page as files, to open in an editor | `make usecase-extract UC=uc-676` |

## Areas

<!-- site: cards -->
| Area | What its use cases cover |
|---|---|
| [Chat](../guide/ops-assistant.md) | Asking the assistant, threads, files in chat, decisions inside a chat |
| [Agents](agents/draft-publish-and-chat-with-an-agent.md) | Drafting, testing, publishing and chatting with agents; their tools, skills and limits |
| [Workflows](workflows/validate-apply-and-test-run-a-workflow.md) | Writing, checking, publishing and running workflows; schedules, retries and replays |
| [Human tasks and cases](../design/human-tasks/task-page.md) | Approvals, reviews, held writes and the case record |
| [Knowledge](knowledge/written-and-pushed-knowledge.md) | Knowledge bases, their sources, search and citations |
| [Files and documents](../guide/data-and-database.md) | Uploads, document types and what is read from them |
| [Tools and apps](tools-and-apps/an-app-key-never-comes-back.md) | Connecting apps and accounts, running tools, keys and the call log |
| [Models](../guide/models.md) | Model aliases, providers and keys |
| [People and access](people-and-access/invite-change-roles-and-remove.md) | Sign-in, members, roles, API keys and the audit trail |
