# Agents version 2: build specs

Status: proposed design, written 2026-11-26. Nothing in this folder is built. The specs cover three releases: 1.4.0,
1.5.0 and 1.6.0.

Version 2 of agents lets a builder describe an agent in one file and get the features of the best agent libraries
without writing a loop: plans, helpers, a sealed workspace for running code, typed answers and teams. Five protections
stay as they are today. This folder holds one build spec per part, a coding guide and the trials that must pass before
parts of the build start. An engineer who has read only this folder should be able to build each part.

## Mission

| Agents gain | Without giving up |
|---|---|
| A published agent library runs the loop, behind a contract of ours | A run can pause for days and survive a restart |
| One declarative, versioned spec file per agent | Each tenant's data is separate |
| An automatic mode that picks direct, plan, helpers or sandbox per request | A person approves any action that changes data |
| A sandbox per conversation for commands, Python and files | Secrets stay behind the model gateway and the tool gateway |
| Teams of agents and people drawn on the workflow canvas | A cost budget |

## Decisions these specs start from

| Decision | Where it is specified |
|---|---|
| Strands Agents becomes the loop. The current library and the half of the kernel that drives it are deleted. Thirteen kernel features are ported. Another loop can be plugged in by our engineers behind one contract | [Runtime contract and Strands loop](runtime-contract-and-strands-loop.md) |
| The budget check and the model-call record move into the model gateway | [Model gateway](model-gateway.md) |
| The sandbox is our service behind Strands' sandbox interface, with swappable backends: Fly Sprites for hosted tenants, Docker and Kubernetes for a firm's own install | [Sandbox service](sandbox-service.md) and its three backend pages |
| An agent is a spec file; the loop defaults to automatic, with seven explicit kinds as an advanced override | [Agent spec file](agent-spec-file.md), [Automatic mode and loop kinds](automatic-mode-and-loop-kinds.md) |
| A chat builder drafts the spec and a person approves it section by section | [Chat builder](chat-builder.md) |
| Workflows gain teams, people as members and human tasks answerable from email and Teams; the workflow engine stays ours, on PostgreSQL and SQL Server | [Teams and human tasks](workflow-teams-and-human-tasks.md), [Workflow durability](workflow-durability.md) |
| The product is not in production: no compatibility migrations, installs are reseeded | [Coding guide](coding-guide.md) |

## Map

| Page | What it specifies | Release |
|---|---|---|
| [Runtime contract and Strands loop](runtime-contract-and-strands-loop.md) | The contract between the agents service and any loop; the Strands driver; the 13 ported features; the event mapping; where pause state lives | 1.4.0 |
| [Model gateway](model-gateway.md) | Budgets and reservations, the replay record, call purposes, cached tokens | 1.4.0 |
| [Agent spec file](agent-spec-file.md), [schema](agent-spec-schema.yaml), examples for [loan operations](agent-spec-loan-ops.yaml) and an [IT helpdesk](agent-spec-it-helpdesk.yaml) | Every field, its validation rules, storage and the save, check and diff routes | 1.4.0 |
| [Automatic mode and loop kinds](automatic-mode-and-loop-kinds.md) | How a mode is chosen and recorded; the eight loop kinds; hand-overs | 1.4.0 |
| [Chat builder](chat-builder.md) | Drafting a spec from a description, in 13 sections, and trying it | 1.4.0 |
| [Evals](evals.md) | Checks for the new behaviour, the publish gate, team tests | 1.4.0, 1.5.0, 1.6.0 |
| [Tool gateway](tool-gateway.md) | Tool-server client additions, web search and page fetch | 1.5.0 |
| [Sandbox service](sandbox-service.md) | Lifecycle, files, the exit gate, approvals, limits, the backend port | 1.5.0 |
| [Sprites](sandbox-backend-sprites.md), [Docker](sandbox-backend-docker.md), [Kubernetes](sandbox-backend-kubernetes.md) | One page per place a sandbox runs | 1.5.0 |
| [Teams and human tasks](workflow-teams-and-human-tasks.md) | Connection kinds, groups, shared notes, tasks, deadlines, undo | 1.6.0 |
| [Workflow durability](workflow-durability.md) | Rebuild from the journal, run budgets, an agent step that pauses, SQL Server statements | 1.6.0 |
| [API](api.md), [OpenAPI draft](openapi-draft.yaml) | Every route added, changed or removed | all |
| [SDK](sdk.md), [CLI](cli.md) | Methods and commands in both languages | all |
| [Console screens](console-screens.md) | Nine screens, their states and components | all |
| [Coding guide](coding-guide.md) | Where code goes, how each protection is enforced and tested, what never to do | all |
| [Trials](trials.md) | Fifteen experiments, each with a pass line, what it gates and a fallback | all |

Every component page has the same sections: purpose; what it owns and must not own; interfaces; data model; flows with
failure paths; settings; security, cost and limits; acceptance criteria as failure modes; use cases per layer; files to
add, change and delete; open points with the trial that settles each.

## Release split

| Release | Ships | Does not ship |
|---|---|---|
| 1.4.0 Agent runtime | The contract and the Strands driver; budgets in the model gateway; the spec file and its routes; automatic mode and the loop kinds that need no sandbox; the chat builder; evals for the new behaviour; the SDK, CLI and console for these | Sandbox, web tools, teams |
| 1.5.0 Sandbox | The sandbox service and three backends; the exit gate; sandbox tools, files and approvals; the tool gateway's client additions, web search and fetch; the function runner folded in; the sandbox mode of automatic | Teams |
| 1.6.0 Agent teams | Connection kinds and groups on the canvas; shared notes; human tasks with roles, deadlines, email and Teams; undo steps; rebuild from the journal; run budgets; an agent step that pauses; the engine fully on SQL Server; team tests | Browser use, voice, branching a conversation, background helpers that outlive a turn |

## Build order and lanes

Each lane is one branch and one builder; lanes in the same row run in parallel. A lane starts when the trials and lanes
it names are done.

### 1.4.0

| Order | Lane | Builds | Needs |
|---|---|---|---|
| 0 | Trials 0 to 3 | | |
| 1 | A. Scripted model seam | The scripted model; kernel tests moved onto it under the current loop | |
| 1 | B. Gateway budgets | Budget tables and routes, reservations, replay, purposes, cached tokens | |
| 1 | C. Spec model | The schema, the spec model, validation rules, storage, the spec routes | |
| 2 | D. Contract and driver | `LoopDriver`, `LoopSeams`, the current loop wrapped as a driver, then the Strands driver | A, trials 1 and 2 |
| 2 | E. Agents ledger removal | The agents service sends budget headers and drops its own ledger | B |
| 3 | F. Feature port | The 13 features on the seams, both drivers green, then the old driver deleted | D, E |
| 3 | G. SDK and CLI for the spec | `apply`, `export`, `validate`, `diff` | C |
| 4 | H. Automatic mode and loop kinds | The mode tool, plan-before-write, helpers, hand-overs, the loops route, the new stream frames | F, trial 3 |
| 4 | I. Evals | New checks, background runs, the gate by digest | F, C |
| 5 | J. Chat builder | Draft and try routes | H, C |
| 5 | K. Console | Agent tabs on the spec, the Loop tab, chat blocks, the trace | H, G |
| 6 | L. Builder screen, use cases at every layer | | J, K |

### 1.5.0

| Order | Lane | Builds | Needs |
|---|---|---|---|
| 0 | Trials 5 to 10 | | Trial 0 |
| 1 | A. Sandbox service core | Tables, lifecycle, files and manifests, the backend port, the Docker backend, images | Trial 10 |
| 1 | B. Exit gate | The proxy, tunnel mode, the two lists, the call log rows, then inspect mode and grants | Trial 7 |
| 1 | C. Tool-server client additions | Structured results, list changes, questions, progress, resources | |
| 2 | D. Sandbox tools | The `sandbox` module in the tool gateway; `GatewaySandbox` in the kernel; the sandbox mode | A, B, trial 6 |
| 2 | E. Kubernetes backend | | A, trial 8 |
| 2 | F. Sprites backend | | A, trial 5 |
| 2 | G. Web tools | Search and fetch | B |
| 3 | H. Thread sandbox routes, SDK, CLI | | D |
| 3 | I. Function runner move | Function runs on the sandbox service; the old service deleted | A, trial 9 |
| 4 | J. Console | The Sandbox tab, the Files panel, commands in chat and the trace | H |

### 1.6.0

| Order | Lane | Builds | Needs |
|---|---|---|---|
| 0 | Trials 11 to 14; the team mocks redrawn and copied into `mocks/` | | |
| 1 | A. Engine durability | Rebuild from the journal; the SQL Server statements | Trials 11, 14 |
| 1 | B. Run budgets | | 1.4.0 lane B |
| 1 | C. Tasks | The tasks routes, kinds, roles, `thenAsk`, escalation on the engine | |
| 2 | D. Agent step pause | The port's pause and resume, turn states | A, trial 13 |
| 2 | E. Connections and groups | Kinds, checks, hand-over ports, ask as a child step, the check loop, group limits, notes | A, trial 12 |
| 2 | F. Notifiers | Email and Teams, signed links, the confirm page | C |
| 3 | G. Undo steps | | E |
| 3 | H. Team tests | | E, C |
| 3 | I. SDK and CLI | | C, E |
| 4 | J. Console | Canvas line kinds and groups, the run page's turns and notes, the inbox | I, the redrawn mocks |

## Done when

| Release | Done when |
|---|---|
| 1.4.0 | No file outside the Strands adapter imports an agent library, and the old library is not installed. Every row of the acceptance tables on the runtime, gateway, spec, automatic mode, builder and evals pages has a test that was seen failing. A turn paused for approval resumes after every process restarts, on both databases, with one write and no model call charged twice. An agent is created from a spec file through the API, both SDKs, the CLI and the console, passes its evals and is published; the use cases ran at all four layers |
| 1.5.0 | The sandbox suite's 12 rows pass on Docker and Kubernetes in CI and on Sprites in staging. A conversation's files survive a three-day pause with every service restarted. A request to an unlisted host is refused and shown with who can allow it. A planted secret appears nowhere inside a sandbox or in any model request. The function runner service is deleted and its tests pass on the sandbox service |
| 1.6.0 | A team of two agents and one role is drawn on the canvas, run, answered from the inbox and from email, and its turns and notes read at all four layers. A worker killed mid-team leaves one journal row per turn on both databases. A waiting run continues across an engine build change. The portable baseline has no engine line. A missed deadline moves a task to the next role |

Each release also needs: `make openapi` and `make sdk-verify` clean; the docs for each changed service updated in the
same pull requests; the trials it depends on recorded in [trials](trials.md).

## Where these specs depart from the design inputs

The design pages these specs were written from are direction. Reviewing them against the code and against each other
led to the changes below. Each is specified on the page named.

| Input said | These specs say | Reason | Page |
|---|---|---|---|
| A Team step holds its members, kind and hand-over map | Members are steps on the canvas; hand-overs, questions and checks are kinds of line; a group frame holds the limits. The Team step is the folded view of a group | A direction given on 2026-11-26: the team should be visible as connected agents, not one level down. It also needs no new engine port and no new journal table | Teams and human tasks |
| Strands' swarm and graph run teams and hand-overs | The runtime and the engine move the work between agents; each agent's turn is its own Strands run | Pausing a library swarm for days is documented only through session managers that write outside our database. Per-turn runs keep budgets, approvals and saved state where they already are. Decided on 2026-11-26; trial 4 is for information only | Automatic mode; Teams |
| The library's session manager can hold a paused run | Our checkpoint holds an opaque loop state | One store, one lease, one encryption key, on both databases | Runtime contract |
| Hosted sandboxes were ruled out on one design page | Fly Sprites is the hosted backend | The later decision replaces that line | Sprites backend |
| A sandbox's files persist with its computer | A copy in the team's storage after every turn is the truth on every backend; a backend's own disk is a fast path | Resume on another server must work on Docker and Kubernetes too, and one deletion rule must cover all three | Sandbox service |
| An approval is tied to a risky command's exact text | Approvals sit where the sandbox cannot avoid them: the file tools and the exit gate | A command can delete or install in more ways than a text rule can list | Sandbox service |
| The exit gate's owner was not stated | The tool gateway runs it | It already owns the host list and the secrets; a third way out would break the two-gateway rule | Sandbox service |
| Plan, skills and typed answers could use the library's plugins | They stay ours, written against the seams | They must behave the same under any loop driver, and they are covered by existing tests | Runtime contract |
| Seven loop kinds | Seven explicit kinds plus automatic; two of them, evaluator and long-running, are thin presets of settings | Kept as the default | Automatic mode |

## Decisions and defaults recorded on 2026-11-26

| # | Point | Outcome | Status |
|---|---|---|---|
| 1 | Who moves a hand-over between agents | Our workflow engine and runtime, not a Strands swarm. Trial 4 is for information only | Decided |
| 2 | Where sandbox approvals are set | At network grants and at writes to saved files, not by reading command text | Decided |
| 3 | Answering outside the console | A person can answer from email or Teams. An approval opens a page where they sign in first | Decided |
| 4 | Sprites | Build on Sprites now. Its terms and regions are checked later and stay an open point, not a blocker | Decided |
| 5 | Loop kinds | Keep the seven explicit kinds beside automatic | Default |
| 6 | Replay rows in the model gateway | Kept for 168 hours, deleted earlier when a run ends | Default |
| 7 | Team mocks | The three team mocks are redrawn for the canvas design before the 1.6.0 console lane | Default |
| 8 | Where final mocks live | Copied into `docs/design/agents-v2/mocks` in this repository | Default |
| 9 | Search provider | A setting, with one adapter shipped: Brave Search | Default |

A row marked "Default" was not ruled on and can be changed without reopening the rest.

## Open points

Each component page lists its own. The trials that settle them are in [trials](trials.md), in running order.
