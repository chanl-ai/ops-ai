# Use cases

Status: current.

A use case is one user-visible behaviour checked end to end through a public surface: the HTTP API, the SDK, the
CLI or the console. This folder is the central testing surface for those layers. Each service keeps its own unit and
integration tests (pytest in the Python services); use cases only drive what a client can drive.

## Run them

| Task | Command |
|---|---|
| Prerequisite: PostgreSQL :5477 and OPA :8181 | `make db-up` |
| One use case, every layer it lists | `make usecase-test UC=uc-001` |
| One layer | `make usecase-test UC=uc-002 LAYER=ui` |
| All of them | `make usecase-test` |
| Registry, one entry, coverage | `make usecase-list`, `make usecase-show UC=uc-002`, `make usecase-coverage SERVICE=agents-service` |
| Register a new one | `make usecase-new SERVICE=<service> TITLE="<title>"` |

Run make under your secrets manager as for the rest of the stack. The scripts do not need model keys and the runner
removes them.

## Rules

| Rule | Detail |
|---|---|
| Scripted model only | A script starts its own agents service on the scripted model (`services/agents-service/scripts/scripted_server.py`) on ports and a database the run owns: free ports picked at start and a database `ops_usecase_r<pid>_<hex>` dropped when the run ends, so two sessions' runs never meet (`OPS_USECASE_*` set explicitly wins). The runner removes `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the script's environment unless `APPROVED_REAL_CALLS=<n>` is set, with n the number of real calls the owner approved |
| A pass needs evidence | A script prints one `PASS <name>` or `FAIL <name>: <detail>` line per check. The runner passes a use case only when the script exits 0, printed no FAIL line and printed at least one PASS line |
| Every use case names its non-vacuous check | The check that fails when the behaviour breaks, often a refusal paired with the success it guards. Each doc says which check that is |
| The status column is not evidence | It records the last state someone saw; only `make usecase-test` decides |
| The console is a production build | A ui run serves the console with `next start` on a build made once per source hash and stack shape (`packages/usecase-runner/src/console-build.ts`, cached in `apps/console/node_modules/.cache/console-build-<hash>`, pruned after three days). A run copies the build and swaps its placeholder service URLs for its own ports, so a cold build costs one run and later runs start in seconds. `OPS_USECASE_CONSOLE=dev` runs `next dev` instead. Dev-only pages (`/dev`, `/preview`) answer because the run sets `OPS_ALLOW_PREVIEW_PAGES=1` |
| Layers that do not exist yet | `sdk` (until `packages/sdk-py` or `packages/sdk-ts` exists) and `cli` (until `packages/ops-cli` exists) report "not available yet; run LAYER=api" and exit 3 when nothing else ran |

## Layout

| Path | Holds |
|---|---|
| `docs/usecases/README.md` | This registry; the runner reads the table below |
| `docs/usecases/<service>/<topic>.md` | The use case, named for its topic, with its id in the header: preconditions, steps and expected results, acceptance layers, non-vacuous check |
| `docs/usecases/<service>/scripts/test-uc-NNN-<layer>.py` or `.mjs` | One script per layer; Python for api, Node with Playwright for ui |
| `docs/usecases/lib/usecase_harness.py` | Checks, the four thread calls, and the scripted services, shared by the Python scripts |
| `packages/usecase-runner/` | Registry parser, layer resolver, PASS/FAIL reporter, exit codes, and the ui harness; `scripts/usecase.mjs` calls it |

Exit codes: 0 every run use case passed, 1 a use case failed or a required script is missing, 2 usage error or a
malformed registry, 3 nothing ran because the requested layer is not available yet.

## Registry

| Id | Service | Title | Layers | Status |
|---|---|---|---|---|
| uc-001 | agents-service | Chat turn with citation | api | passing |
| uc-002 | agents-service | Write tool pauses and approval resumes with step-up | api, ui | passing |
| uc-003 | agents-service | Simple workflow through the four thread calls | api, ui | passing |
| uc-004 | agents-service | Complex workflow with fan-out, grade loop, review pause and send | api | passing |
| uc-005 | agents-service | A pause survives a restart | api | passing |
| uc-006 | agents-service | SLA timer breach escalates | api | passing |
| uc-007 | tools-service | A tool write without a token is refused | api | passing |
| uc-008 | agents-service | A paused workflow is decided from the console | api, ui | passing |
| uc-009 | agents-service | Self-approval is refused | api | passing |
| uc-010 | tools-service | A builder manages a tool module | api, ui | passing |
| uc-011 | tools-service | A tool call runs through the registry and is logged with its caller | api | passing |
| uc-012 | tools-service | A builder imports tools from OpenAPI and MCP and calls them on allowed hosts only | api, ui | passing |
| uc-013 | tools-service | A tool's credential is a secret that never comes back | api, ui | passing |
| uc-015 | tools-service | Tool module details page | ui | passing |
| uc-018 | agents-service | Create, edit, publish an agent and chat with it | api, ui | passing |
| uc-019 | agents-service | Create a workflow from draft JSON, validate, test, publish and start it | api, ui | passing |
| uc-020 | agents-service | Chat starts a workflow | api, ui | passing |
| uc-021 | platform-service | Sign in, session, refresh, sign out | api, ui | passing |
| uc-023 | platform-service | Members and roles | api, ui | passing |
| uc-025 | platform-service | Audit | api, ui | passing |
| uc-026 | platform-service | Anonymous and dev boundary | api | passing |
| uc-027 | agents-service | An approval outlives its token | api | passing |
| uc-028 | agents-service | An agent runs on the model its publisher chose | api | passing |
| uc-038 | tools-service | A failed tool call says which side failed, and a test call reaches the real system (live, OPS_LIVE_EGRESS=1) | api | passing |
| uc-040 | tools-service | Security decides a tool module review | api, ui | passing |
| uc-041 | tools-service | Workflow approvals use agents-service workflows | api | passing |
| uc-042 | tools-service | A module's call counts and activity come from real calls | api | passing |
| uc-047 | console | Sub-pages show as rows in the sidebar | ui | passing |
| uc-048 | agents-service | An agent is granted and calls a published tools-service operation | api | passing |
| uc-049 | agents-service | A write runs only after as many people as its policy names approve it | api | passing |
| uc-052 | console | Access is Read or Write in the console | ui | passing |
| uc-053 | console | The requester cannot approve a workflow's access; another person can | ui | passing |
| uc-054 | console | Import presets access per operation and asks for no connection | ui | passing |
| uc-055 | console | A bank API goes from import to a governed agent call | ui | failing |
| uc-056 | console | A grant no longer offered shows as stale and can be removed | ui | passing |
| uc-057 | console | A write held in a chat is listed in Reviews and approved there | ui | passing |
| uc-058 | console | Another person's chat stays private: a teammate gets 404 (owner decision, c7ebccb) | ui | passing |
| uc-059 | console | A builder sets a write's approval policy on the module page | ui | passing |
| uc-060 | models-service | An alias reaches the fake OpenAI or the real one by its connection's base URL | api | passing |
| uc-073 | console | Chat widgets draw by shape on the dev widget page | ui | passing |
| uc-074 | console | The chat thread draws a cited answer and a tool call with AI Elements | ui | passing |
| uc-080 | kb-service | A banker asks an agent and gets an answer cited by page and section from uploaded PDFs | api | passing |
| uc-061 | console | Tool results draw as widgets by shape through chat | ui | passing |
| uc-072 | console | A banker decides a drafted write inside the chat | ui | passing |
| uc-075 | console | A department's PDFs become a cited answer through the console on kb-service | ui | passing |
| uc-078 | console | The advisor's helper answers about a customer and compares products | api, ui | passing |
| uc-079 | console | The branch policy agent answers from the manual or says it does not know | api, ui | passing |
| uc-084 | agents-service | An agent finds a workflow with search_tools and runs it; its agent step answers by schema | api, ui | passing |
| uc-081 | agents-service | Basic workflow nodes run through the queue, and a worker killed after the tool step leaves the tool called once | api, ui | passing |
| uc-085 | agents-service | An agent refuses a blocked topic before answering, through a guardrail it pins by version | api, ui | passing |
| uc-086 | console | A builder takes a bank API from import to a governed agent call | ui | passing |
| uc-087 | console | A banker finds, starts and continues chats: suggested prompt, regenerate, stop, retry, server search and paging | ui | passing |
| uc-088 | agents-service | A builder sets the limits callers override within and publishes them with the agent | ui | passing |
| uc-089 | console | An agent shows a table and a figure in chat with no tool behind them | ui | passing |
| uc-090 | console | A builder edits an operation's input, access and approval policy and sees its secrets | ui | passing |
| uc-091 | console | A banker narrows the agent for a thread within its limits and attaches a file it cites by page | ui | passing |
| uc-092 | agents-service | A builder designs a workflow in forms, publishes it through review, pauses, resumes and cancels a run | ui | passing |
| uc-095 | console | An agent fills a pinned widget and lays out its own in chat | ui | passing |
| uc-093 | files-service | A member stores a file once and it is downloaded, held and deleted under its rules | api | passing |
| uc-094 | files-service | Another team's file is missing on every files-service route | api | passing |
| uc-096 | console | Knowledge bases work end to end from the console: create, add files and a page, watch ingestion, test a question, retire | ui | passing |
| uc-097 | console | A builder saves create dialogs and account settings with Enter, and Cancel never saves | ui | passing |
| uc-098 | console | A builder pages and searches a growing list on the server | ui | passing |
| uc-099 | console | A viewer sees the team's records read-only | api, ui | passing |
| uc-100 | console | The console matches the page plan: Overview, no Templates, Conversations under Chat, reviewer | ui | passing |
| uc-103 | console | A builder edits a widget with forms; JSON stays the advanced view | ui | passing |
| uc-104 | console | A guardrail has its own page and an agent pins one of its versions | ui | passing |
| uc-105 | console | A Security admin sets where each purpose stores its files and with which credential | ui | passing |
| uc-108 | console | A chat shows when its budget is spent and the person continues; an admin raises it | ui | passing |
| uc-109 | console | An agent embedded on an intranet page answers from another origin; an unlisted origin is refused | ui | passing |
| uc-116 | console | A builder issues and revokes the mint key a bank's server starts widget sessions with; a viewer sees no key controls | ui | passing |
| uc-119 | console | A bank page shows the full chat through the loader and the embed app; approvals wait for Human Tasks; forged messages and other pages are refused | ui | passing |
| uc-117 | agents-service | A bank's server mints a widget session with the deployment's key; the chat's approval is decided through Reviews | api | passing |
| uc-110 | console | A Security admin adds a secret and a host with Enter, and Cancel sends nothing | ui | passing |
| uc-101 | console | A builder builds and debugs a tool operation on its full-width workbench: draft mock and transform, a typed secret, the request sent | ui | passing |
| uc-106 | console | Lists tab once per row, mock-backed pages say Preview, and versioned settings save from the button | ui | passing |
| uc-107 | console | A Security admin manages every secret in one place: usage, rotation reaching every operation, refused delete, team scope | ui | passing |
| uc-111 | platform-service | A person stays signed in across make up: the database migrates in place, never wiped on a chain mismatch | ui | passing |
| uc-112 | console | A builder works the Files page on files-service: views, search, references, download, guarded delete, an admin's hold | ui | passing |
| uc-113 | console | A builder picks a knowledge base past the first hundred and a tool, searched on the server | ui | passing |
| uc-118 | platform-service | An admin reads the roles and their grids, what each person may do in shared teams, and a role change reaching the next token | api | passing |
| uc-115 | console | A run shows its workflow graph read-only with what passed, failed and was skipped | ui | passing |
| uc-114 | agents-service | An admin decides which publishes need a review: never publishes at once, always opens a review, a builder cannot change it | ui | passing |
| uc-121 | console | A builder designs a workflow on a canvas that fills the page at a readable zoom | ui | passing |
| uc-122 | console | A builder edits steps in a side sheet and adds them from a tabbed panel | ui | passing |
| uc-123 | console | Run and review controls show only to roles that can use them | ui | passing |
| uc-125 | console | A page on sample data says so and cannot be saved, while a live setting persists | ui | passing |
| uc-126 | console | The proposed settings tree is a mock a reviewer can walk: one set of cards, Find, locks, dialogs that are the same forms as the pages | ui | passing |
| uc-127 | console | The live console's fields are lighter than the page, widget columns resize, tab labels fit, record lists select and show ids | ui | passing |
| uc-152 | console | The live settings follow the approved tree: a settings sidebar with Find, and moved pages that old routes redirect to | ui | passing |
| uc-170 | console | Govern > Policies lists the workspace's policies from platform-service, a Security admin saves one, a builder is told he cannot see them | ui | passing |
| uc-124 | agents-service | A workflow turns an uploaded invoice into fields a person can check | api | passing |
| uc-128 | agents-service | Chat starts on the team's default agent, which asks specialists; @ hands the chat over and back | api, ui | passing |
| uc-130 | console | An agent's Channels tab shows its chat default, embeds with sites, keys and usage, and calling workflows; an embed retires for good | api, ui | passing |
| uc-132 | console | The agent shows every generic widget kind in a chat, each drawn once from its schema-checked data | ui | passing |
| uc-133 | agents-service | A test reply shows the knowledge searched and cited, the tools called and where it would pause | ui | passing |
| uc-134 | agents-service | An agent remembers each person; they list, correct, export and forget what it keeps | api | passing |
| uc-135 | agents-service | People see, correct, forget and export what an agent remembers about them, from the chat | ui | passing |
| uc-136 | console | Embedding an agent's chat works from the console: the mint-key snippet, Chat widget under New deployment, and no embed button for whoever may not change the agent | ui | passing |
| uc-137 | console | A changed publish review setting applies to the next tool module publish, with no restart | ui | passing |
| uc-138 | console | Knowledge, source and file pages follow what the caller may do with each record | ui | passing |
| uc-139 | console | The console works cases: the list with both deadlines, server filters, a case's timeline, and runs under Workflows | ui | passing |
| uc-140 | console | The demo walk on the shared stack: cited chat, a guardrail, a bank read, a held write approved, a run's agent step, a workflow as a tool, and the levy mailbox | ui | failing |
| uc-141 | console | The one Activity page lists a run by name, filters by kind on the server, narrows to a source, and opens the run | ui | passing |
| uc-142 | console | Channels on real data: the hub, tab dots and an email landing match /v1/channels; Deployments lands on Channels; an embed's version changes in its row | ui | passing |
| uc-143 | console | Access › Tool access lists every workflow's tool access by view, counted on the server | ui | passing |
| uc-129 | kb-service | A builder adds documents to a knowledge base by uploading them or picking them from Files | ui | passing |
| uc-160 | platform-service | A person resets their password by a mailed link and signs in with it; the demo password stops working for them | api | passing |
| uc-161 | platform-service | A first OIDC sign-in creates a chat-only member once, and the console offers SSO for that email | api, ui | passing |
| uc-162 | platform-service | A person signs in through SAML and steps up at the same provider, which must ask again | api | passing |
| uc-163 | platform-service | A password in an SSO-only workspace, another provider's answer and a reused code are refused | api | passing |
| uc-164 | platform-service | Workspace admins create a team with its first admin, rename, archive and restore it; others cannot | api, ui | passing |
| uc-212 | platform-service | A workspace sets its security and default teams, and SSO groups put new people in mapped teams | api | passing |
| uc-213 | platform-service | A Security admin sets an OIDC provider on Settings > Sign-in, and its domain routes sign-in only once its DNS TXT record is verified | api, ui | passing |
| uc-214 | platform-service | Five wrong passwords lock sign-in and step-up for fifteen minutes, reset mail is capped at three an hour, and a reset ends the lock | api | passing |
| uc-215 | platform-service | A SAML provider with signed requests and required encryption signs a person in; another key, old key transport and a plain assertion are refused | api | passing |
| uc-216 | platform-service | A person invited as a viewer reads the team's work, changes none of it, invites nobody and acts in no other team | api, ui | passing |
| uc-217 | platform-service | A person invited as a builder creates and edits agents and asks to publish, but decides no review and changes no members or policies | api, ui | passing |
| uc-218 | platform-service | A person invited as a reviewer decides a builder's publish request and edits no agent | api, ui | passing |
| uc-219 | platform-service | A person invited as an admin invites, changes a role that reaches the next token and removes a member, only in their team, never the last admin | api, ui | passing |
| uc-220 | platform-service | A person invited as a Security team admin sets sign-in providers and policies, another team's admin cannot, and the right moves with the security team | api, ui | passing |
| uc-165 | console | The channels mock connects a mailbox with a secret from Secrets, tests it, and a workflow trigger picks it | ui | passing |
| uc-150 | agents-service | An email with a PDF in a watched mailbox starts one workflow run, with the PDF in Files; a redelivery starts none | api | passing |
| uc-151 | console | A builder sets up Email received on the canvas: team mailbox, folder and filters | ui | passing |
| uc-192 | agents-service | An email with a PDF in an IMAP mailbox (GreenMail) starts one workflow run through tools-service, the password a Secrets-page secret | api | passing |
| uc-199 | agents-service | A builder connects a team mailbox, tests it, binds a workflow, pauses and resumes it; mail starts runs only while it runs | api, ui | passing |
| uc-200 | agents-service | A send_reply naming a team mailbox leaves from its own sender (Mailpit), once per key; another team's call sends nothing | api | passing |
| uc-209 | agents-service | A Start workflow step starts one live child per list item in the parent's team, keyed so a retry starts none twice; a test run's children are test runs | api | passing |
| uc-210 | agents-service | A levy notice in the levy mailbox runs on the workflow runner: one case per debtor, name-only debtors not matched, a 422 hold back to review, a redelivery opens nothing | api | passing |
| uc-223 | agents-service | A PDF and a CSV mailed through GreenMail become levy cases in one child run each; refused files are skipped, a low read waits for a person, the reply leaves from the mailbox | api | passing |
| uc-224 | agents-service | A person corrects a document read in Human Tasks and sees the reply and cases | ui | passing |
| uc-225 | agents-service | A reviewer takes a workflow Human Task and sees its deadline | ui | passing |
| uc-226 | agents-service | A mailbox workflow takes every shape of email | api | passing |
| uc-227 | console | A file is read on its own page: Preview, Extract with a document type, each field with its confidence and quote, and Read as on the Files list | ui | passing |
| uc-228 | console | Starting a run from the list and the editor, and a run and a case on their own pages, with screenshots for a before-and-after comparison | ui | passing |
| uc-243 | documents-service | Builders manage document types, versions, samples and test runs in the console | ui | passing |
| uc-244 | agents-service | Extract on a file saves what was read, and deleting the file purges it | api | passing |
| uc-229 | agents-service | A guarded answer streams as it is written and is replaced when its check fails | ui | passing |
| uc-230 | tools-service | A workflow step notifies an outside system's webhook with a case's data | api | passing |
| uc-231 | agents-service | A Calculate step works out a levy's amount and deadline | api | passing |
| uc-232 | console | The header names the workspace from platform-service and Tools › Workflows lists the registry directory, not the mock | ui | passing |
| uc-245 | agents-service | A team's mailbox runs end to end: connected and tested in the console, bound through a review, a PDF read, checked and decided by a person, a case opened, the reply sent from the mailbox, a redelivery ignored | ui | passing |
| uc-246 | agents-service | A mixed levy email is read by kind in parallel: a case and a webhook per document, a person checks the doubtful read, and the sender gets a reply | ui | passing |
| uc-247 | agents-service | A builder tests an agent on a real chat thread the server marks test | api | passing |
| uc-253 | agents-service | A builder tests an agent in the right panel of its page, with the chat page's components | ui | passing |
| uc-254 | agents-service | A builder copies a task type and an API caller opens typed Human Tasks | api | current |
| uc-258 | agents-service | A Classify step routes a message by meaning, and is off until the team turns AI steps on | api | current |
| uc-259 | agents-service | A Summarise step summarises text, and an answer outside its schema takes the error port at once | api | current |
| uc-260 | agents-service | An Extract from text step reads fields from a message | api | current |
| uc-261 | agents-service | A Draft step writes a reply and sends nothing | api | current |
| uc-262 | agents-service | One workflow classifies, summarises, extracts and drafts on the fake model | api | current |
| uc-263 | agents-service | A typed task opens with task assist when the team turns it on | api | current |
| uc-264 | console | Every page draws the shared header | ui | current |
| uc-265 | agents-service | Personal data is masked in an agent's replies, stored messages and workflow step output | api | current |
| uc-266 | tools-service | A workflow's write is checked against the team's sending policy before it goes out | api | current |
| uc-390 | tools-service | A tool signs in with an API key from its connection, in a header or the query, by environment | api | current |
| uc-391 | tools-service | A tool signs in with a username and password from its connection, by environment | api | current |
| uc-392 | tools-service | A tool signs in with a bearer token from its connection, by environment, and a replaced token reaches the next call | api | current |
| uc-393 | tools-service | A tool signs in with an OAuth client ID and secret: one token, reused, fetched again after a 401 on a read, never resent on a write | api | current |
| uc-394 | tools-service | A person signs a connection in once with the team's account, and tools use and refresh its token | api | current |
| uc-395 | tools-service | A tool presents a client certificate from its connection to a system that requires one | api | current |
| uc-396 | tools-service | A builder adds an MCP server behind OAuth by its address, signs in once, and its tools run through the same executor | api | current |
| uc-397 | tools-service | A workflow's tool step reaches its error and timeout ports on mock answers in a test run, and live reaches the system | api | current |
| uc-410 | tools-service | An assistant lists and runs a team's read tools over MCP with an API key; writes, other teams and production are refused | api | current |
| uc-267 | console | Admins see roles, a person's effective access and why an action is refused | ui | current |
| uc-233 | console | Start run is a form generated from the trigger's input schema; a file input uploads or picks files and the run gets their ids | ui | passing |
| uc-234 | console | A Human Task opens as its own page: the question, the document beside the read values, Details folded, and the decision in a footer row that never covers the body | ui | passing |
| uc-257 | console | Tables size each column by what it holds: names trimmed to one line with the whole value on hover, numbers right-aligned, a dash for an empty cell, and the name pinned on a phone | ui | passing |
| uc-248 | agents-service | A hold on a customer's account: matched, worked out, approved in time or by a supervisor after the deadline, placed, noted on a case, and the outside system told | ui | passing |
| uc-249 | agents-service | A complaint email: each attachment recognised and its read kept, the complaint read and triaged by an agent, a case by urgency, a hold started, and an approved reply | ui | passing |
| uc-251 | agents-service | A case reads assembled: typed fields in its case type's order, what it waits on and the drafted action, its run, workflow and file; decided on the task page, the action reads decided | api | passing |
| uc-252 | agents-service | A builder archives a workflow: it starts no run and leaves both lists, its run kept; restored, it serves its live version again | api | passing |
| uc-400 | agents-service | A workflow forks into two checks and a Join: the step after it runs once with both by the step they came from; a skipped branch is null; a fork meeting at a plain step is warned | api | passing |
| uc-401 | agents-service | A never-run workflow's steps list their output fields by port, from type, settings, answer or operation; a misspelt mapping is warned on save | api | passing |
| uc-402 | agents-service | A parent reads three attachments in children two at a time, one fails, and goes on once with every result in item order | api | passing |
| uc-403 | agents-service | A workflow waits two seconds, waits until a date or goes on when it is past or not a date, and a waiting review is reminded in Activity until decided | api | passing |
| uc-331 | files-service | A file is read with Detect from the Files page | api, ui | passing |
| uc-398 | console | A crafted PDF runs no script in the viewer | ui | current |
| uc-399 | kb-service | People and services read knowledge usage, refs, search and workflow refs on one route each | api | passing |
| uc-256 | console | A case page says what it is about, what it waits on and what is next | ui | current |
| uc-404 | console | The console says when its services are out of reach, when a session has ended and when a linked task is gone | ui | current |
