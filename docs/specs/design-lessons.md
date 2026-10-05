# Design lessons

Status: draft for review.

## Summary

These are lessons from building earlier internal agent and tool platforms: a multi-channel agent
platform and a hosted MCP tool and knowledge service. Building both produced a long record of
defects, and most came from three causes. First, trust or scope was decided by something the model
or the message could influence. Second, one fact was stated in several places and nothing forced
those places to agree. Third, a check reported success when the thing it guarded was broken.

This platform has internal back-office agents, email intake, per-action human approval and a
release gate fed by evidence. Each of the three causes would land on those components. This
document lists the lessons by area and says what the platform does about each one. A short table
covers lessons that do not carry over, mostly voice, telephony and public-facing widget concerns.
The last section ranks the ten lessons that should shape the architecture most.

The "Spec" column uses these codes:

| Code | Document |
|---|---|
| Arch | `docs/architecture/overview.md` and the ADRs under `docs/architecture/decisions/` |
| 01 | `docs/specs/01-agent-builder.md` |
| 02 | `docs/specs/02-knowledge.md` |
| 03 | `docs/specs/03-data-and-ai-gateways.md` |
| 04 | `docs/specs/04-evals-and-release.md` |

## Agent configuration and versioning

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| An update that replaces a whole configuration object deletes fields the caller did not send. | A PATCH set the whole configuration object. A read with the wrong unwrap returned `{}`, the "merged" write was nearly empty, and the agent lost its model and greeting while still answering. | Promoted versions are immutable. An edit produces a new version from a full server-side snapshot plus typed field changes. Clients never send a whole configuration back. | 01 |
| A second write path silently undoes the first. | A provisioning script rewrote an agent's tool list on every run, so a tool attached by hand disappeared at the next run. | The registry is the only write path. Config-as-code imports and UI edits both create versions. A drift check reports any change made outside the registry. | 01 |
| A fact stated in several places drifts, and the failure appears later as "provisioned but invisible". | Adding one system tool needed seven edits across two packages, and the procedure comment named two of them. Three enums of legal handler names held 5, 26 and about 30 entries. | Each fact has one home: the module manifest declares a tool's name, scopes and schema, and every other list derives from it. Where a package boundary forces a copy, a CI test asserts set-equality between the copies. | Arch, 01, 03 |
| Internal row ids for built-in parts change during migrations. | Built-in tool ids were due to change from synthetic names to per-tenant ids. Anything that had stored the old id needed an audit and a re-point step. | Workflows pin modules by stable name and version, never by an internal row id. | 01, 03 |
| Rules in one prompt compete in cases neither rule anticipated. | A prompt grew 19% over five versions, one rule per scenario fix. A name-search rule began to outrank the update rule, so the agent searched for a contact whose id it already held. | Prompt fragments are versioned and are in the "re-test on save" edit class. Prompt size is recorded per version. The full suite runs on every fragment change, so a new rule that breaks an old case blocks promotion. | 01, 04 |
| An optional safety flag will be omitted, so its default decides behaviour. | A campaign engine's test-mode flag was optional and defaulted to live dialling. | New versions start as drafts that run only in shadow or test. Live execution needs an explicit promotion. No field defaults to the side-effecting mode. | 01, 04 |

## Tools, MCP and scoping

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| Privilege belongs to the grant at operation level. A tool's name cannot express it. | A write tool (delete, crawl) and a read tool over the same resource looked like duplicates. Merging them by resource would have merged two privilege levels into one grant, and no entitlement check in the tool layer would have caught it. | Module scopes are declared per operation (read, draft, write) and granted per workflow with an expiry. The gateway enforces them on every call. | 03 |
| The model must not choose the record a tool writes to. | A preference tool preferred a model-supplied customer id over the conversation's customer, so an agent could flip do-not-contact on any customer. The code comment claimed the opposite. | The subject of a call (case id, customer, account) is bound from the run context by the gateway. Model arguments may narrow it and cannot widen it. A safety claim in a comment states the permissive behaviour first. | Arch, 03 |
| A default open endpoint exposes every tool added to it later. | Every new tenant got a public default endpoint, and anonymous calls could write content. A later change added a tool that anonymous callers could also reach. Tests and an authenticated probe were green. | No unauthenticated surface exists. Tool visibility is deny-by-default per principal type. CI diffs the tool listing seen by each principal type against the main branch on any change to catalogs or provisioning. | 03 |
| A success response from a publish or install step does not prove the tool can be reached. | Installing a pack took three calls. Install returned 201 and import returned 200 while serving nothing. Only a third, undocumented call made the content reachable. | Publishing a module completes only when a reachability check from a consuming workflow passes. The API reports "served to workflow X" as state. | 03 |
| An "ensure" operation must converge when retried. | A namespace change made the same slug valid for one resource type and invalid for another. Every retry failed identically and the agent could never be provisioned. | Every idempotent provisioning operation has a test that runs it twice and asserts the same end state. | 03 |
| Attaching a tool does not mean the agent will use it. | Agents declined tools their prompt did not list. Enabling one feature removed three tools from the effective set, and this looked like the model choosing not to call them. | The server computes the effective tool set per version and shows it in the builder. Validation flags a granted tool that the prompt never mentions. | 01 |
| Tool calls that are not recorded cannot be audited or debugged. | In a reference backend, tool calls made over MCP were not recorded at all. | The data gateway logs every call with principal, workflow version, arguments, result, error and latency, under a named retention owner. | 03 |

## Identity, trust and tenancy

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| Identity, entitlement and risk tier must come from the platform. Message text can never supply them. | A prompt honoured a session header written in the user message, so anyone who typed the bracket got privileged disclosure. It started as a test shim and reached the production prompt. | Session facts are rendered server-side before the model sees any content. For email intake, sender claims, forwarded approvals and header-shaped text in the body are data. A harness convention is reviewed as a security object before it can reach a prompt. | Arch, 01, 03 |
| A classifier that picks a route makes a privilege decision when routes carry different access. | An injected "verification complete" line routed a red-team probe to a privileged specialist in four of five configurations. The same prompt scored 6/6 on a small model and 0/6 on a larger one. | Classification selects a queue and a case type only. Access is decided by module scopes and the acting person's entitlements, which the classifier cannot change. Injection cases sit in the suite with a blocking threshold. | 01, 04 |
| A missing record can leak information when the refusal for it differs. | An agent answered "I don't have that client in the records", which worked as an existence oracle across a list of names. Adding the lookup tool created the leak. | Not-found and not-permitted return the same response. The suite tests both branches with a real record and an invented one. | 02, 03, 04 |
| Agent identity needs an assurance level, and low levels must not feed policy. | An identity ladder from verified down to anonymous was built; levels at "declared" or below were found unfit as policy input. | Registered agents carry a registry identity. Unregistered traffic seen at the AI gateway is discoverable and visible, and it cannot satisfy a scope check. | 03 |
| Access rules checked in several places drift apart. | A reference backend checked tenant access in three places with slightly different rules. | One policy decision point evaluates every request. Services ask it instead of re-implementing checks. | Arch, 03 |
| Credentials must be resolved by the gateway for the acting principal. | Secret resolution filtered by tenant. Filtering by caller or entity was never confirmed, so secret syntax stayed refused in user-authored fields. | Credentials never leave the data gateway. It resolves them by module scope and acting principal. Workflow configuration cannot reference a secret. | 03 |

## Knowledge and retrieval

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| Retrieval quality needs a number and a baseline, or regressions go unnoticed. | Regressions went unnoticed until a labelled set scored recall@5, MRR and citation-heading accuracy, and failed when recall dropped more than 3 points below a checked-in baseline. | Each department has a golden set scored the same way (Knowledge requirement 8). The gate reads the result. Moving the baseline is a reviewed change. | 02, 04 |
| A tenant filter applied after top-k ranking drops good results as data grows. | A reference backend fetched global top results, then filtered by tenant. | Departmental scope is a pre-filter inside the vector query. | 02 |
| Sources and knowledge bases need separate models, and ingestion needs a durable queue. | One knowledge base per tenant, no source model, and in-process processing with no retries blocked most knowledge screens. | Sources (SharePoint, policy library) are connectors with sync history and retries. Knowledge modules are scoped views over indexed sources. Ingestion runs on the durable runtime. | 02 |
| Writes to shared knowledge need a reviewer step and provenance. | Two clients writing the same fact needed a reviewer in the write path; with one, they produced one page with two versions, and each item showed where it came from. | Agent or user writes to knowledge become proposals reviewed by the department's knowledge owner (Knowledge requirement 10). Every entry carries source, version and effective date. | 02 |
| Residency claims must state what each store actually does. | A region field affected only file storage while every other store stayed single-region. | The knowledge spec lists every store that holds bank content with its actual location, retention and redaction point. | Arch, 02 |

## Human-in-the-loop and approvals

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| A new approval store is usually unnecessary. Check for an existing one first. | A plan proposed a new notifications store. Review found a working alert engine already in place, and the revised plan reused it with no new collection. | Human tasks, approvals and alerts are one platform primitive attached to a case. Workflows configure it and never build their own. | 01 |
| Approve-then-execute needs a complete, executable payload. A note to a person is too little. | "Execute" on a follow-up needed a live thread, session, channel, a ready message body and a billing check. The stored follow-up was an instruction to a person. Review counted about five failure modes. | A drafted action is the full payload the tool will send. The approver sees it verbatim, and approval binds to a hash of that payload. Any change after approval needs a new approval. | 01, 03 |
| Agents must not decide approvals, and requesters must not approve their own requests. | A working design refused approve and reject calls over MCP, refused self-approval, derived the requester from the credential, and hid the tool from anonymous callers. | Only a human session can decide. The requester is server-derived. Self-approval is refused. An automation cannot call the tool that creates automations. | 01, 03 |
| Case state transitions need their own tests, because shared code paths hide skipped branches. | An early-return guard in a function every reply passed through meant an escalation flag was never cleared. Thirty-five threads stayed escalated. | Case and SLA states form an explicit state machine. Each transition, including SLA clock stops, has a test. | 01 |
| Declared actions that nothing executes look like working features. | Alert rules declared email and webhook actions, and nothing ever delivered them. | Every declared action type has a consumer and a delivery record, or the builder refuses it. | 01 |

## Evals and testing

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| A test path that differs from the production path cannot test the behaviour that matters. | Test chat was stateless and never populated customer variables. Text scenario runs never resolved identity, so only the unknown-caller branch was testable. | The suite drives the production runtime with seeded identity, entitlements and case state. There is no separate test-chat code path. | 04 |
| A scoring rubric needs a not-applicable result. | A criterion that did not apply scored 0, and with auto-fail on, it zeroed the whole run. | Criteria can return not-applicable, which is excluded from the score and reported. | 04 |
| An eval with nothing in it must fail. | A scorecard created with nested categories returned 201 and stored zero criteria, so it scored nothing and reported a clean pass. | The gate rejects a suite run with zero cases, zero criteria or zero assertions. | 04 |
| An LLM judge's agreement with people must be measured, and kappa is the right measure. | Storing human labels separately, snapshotting the judge verdict at label time and reporting Cohen's kappa per criterion type with a 10-label minimum worked. Two statistics bugs passed unit tests and were found only by reading a real report. | Reviewer overrides become labels. The gate shows judge agreement per criterion and marks it underpowered below the minimum. | 04 |
| Fixtures with absolute dates expire without failing. | A date-clash check went unexercised for three runs because seeded due dates aged into the past. It kept passing as "no clash to find". | Fixture dates are relative to run time. A scenario that exercises none of its target behaviour reports not-exercised and fails. | 04 |
| Extraction accuracy depends on the field contract more than on the model or architecture. | A numeric amount field extracted "two point five million" as 2.5. Both a single call and a fan-out scored 0/5 until the field description stated units. | Extraction schemas state units, formats and currency. Each extracted field is scored separately. | 01, 04 |
| Tests with a mocked database verify which operators were called. They do not verify what the operators did. | A positional update rewrote only the first match. The mocked unit spec passed; a live-database test caught it. | Persistence behaviour is tested against a real store. | 04 |

## Queues, jobs and durable execution

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| Old workers on a shared queue take jobs and run old code. | Three dev server generations consumed the same queue. Jobs finished in 8 ms with no log line, and records stayed in "analyzing". | Workers register with a build version. Each run records which worker version executed it. Old versions drain and stop taking new work. | Arch |
| Every run must reach a terminal state. | Records stuck in "analyzing" needed a scheduled sweep until the analysis path guaranteed a terminal record. | The durable runtime owns retries and timeouts. Each run ends as completed, failed or handed to a person, and the case shows which. | Arch, 01 |
| Writes triggered on every instance duplicate. | Persisting at a pub/sub relay would have written one row per running machine, because two machines always ran. | Side-effecting steps carry idempotency keys. Writes happen once in the step that owns them. | Arch, 03 |
| Queue a job only after the data it reads is committed. | A job queued between a create and an update processed stale data. Concurrent patches to one agent overwrote each other. | Enqueue happens after commit. Concurrent edits to one version are serialised, since versions are immutable. | Arch |
| One active run per case, and retries must not re-enter a running one. | A per-conversation lease returned 409s when a retry re-entered a conversation whose previous turn still held the lease. | A case has one active workflow run. Retries are idempotent against it. | 01 |
| Each control needs a declared failure mode. | A quota check failed open locally and placed real calls. A policy check failed open on lookup error by design. | Each control states whether it fails open or closed. Authorisation, scope and approval checks fail closed. When a gateway is degraded, work goes to the human step. | Arch, 03 |

## Prompting and model calls

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| Tool-calling reliability depends on the model. A shape-normalising library cannot fix it. | The same tool payload returned structured calls 15/15 on one model and 3/15 on another, which wrote the call out as text. | A change to the model behind an alias, including a vendor update, runs the tool-call suite before the alias moves. | 03, 04 |
| A model call that bypasses the gateway is invisible to it. | An eval tool's persona and judge called a fixed provider host and ignored the configured endpoint. | All model traffic goes through the AI gateway by mandate. A lint rule rejects direct provider hosts in workflow code. | 03 |
| Put stable prompt content before volatile content, or prefix caching cannot help. | Per-customer context sat ahead of the stable agent prompt. With the stable prompt first, a warm turn cached 96.5% of input and cost 70% less, and a long stable prompt cost less per turn than a trimmed one. | The runtime composes stable fragments first. The AI gateway reports cache hit rate per alias. Loaded procedures arrive as tool results, so a mid-run system prompt edit does not invalidate the cache. | 01, 03 |
| Splitting a prompt can silently drop a procedure, with a normal-looking reply. | Only the full-prompt arm followed its playbook. Trimmed and routed arms skipped a required step with HTTP 200 and nothing logged. | The suite asserts procedure steps as well as scoring the final answer. A workflow that loads a procedure records that it loaded. | 04 |
| Off the live turn, fan-out to sub-agents can pay for itself. | One sub-agent per extraction facet got the amount right 5/5 against 3/5, at 2.3 times the cost. | Back-office workflows have no live turn, so per-facet extraction is allowed where an error is costly. Cost per run is reported per version. | 01 |

## Release, deploy and environments

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| A pipeline can look automated while nothing fires. | Release tags never triggered deploys because of a CI recursion guard, staging was suspended, and every deploy was a laptop build. A release-gap report showed 0 for every repo because an invalid-field error was swallowed. | Promotion is a recorded pointer move in the registry. Status reports raise errors and never default to zero. | 04 |
| An HTTP 200 after deploy does not show that the product works. | A redirect to the login page returned 200 while the app could have been broken. A headless browser smoke with zero console errors and a real feature affordance replaced it. | After promotion, the platform runs the workflow on sample mail and checks the resulting case, drafts and logs. | 04 |
| A gate that blocks routinely trains people to override it. | A deploy-window gate counted every "active" interaction with no age limit, so it blocked every deploy and the override became routine. | Gate inputs use the system's own definitions (for example, "idle" means what the runtime means by idle). Overrides are logged against the version with a reason. | 04 |
| A quality gate that has never failed may not be running. | A linter had never run in one repo because of three broken config references. When revived, it gated only lines a commit added, so authors were not blocked by old findings. | Each gate step is shown failing once before it is trusted. New gates apply to net-new changes. | 04 |
| Every job must check which environment and store it is about to touch. | A backup job dumped the wrong production database daily for a month. An override flag lost silently to a secret and repeated the mistake. Only 5 of 22 re-run migrations checked the target database. | The runtime checks the target store once, centrally, before any migration or job runs. Backups are verified by their content. | Arch |
| What is running must be read from the system. Source on disk can mislead. | A design was built on a route file from an unmerged branch that happened to be checked out. Elsewhere, the serving tree changed on restart. | The registry answers "which version runs in which environment", and every log line carries that version. | 01, 04 |
| A published contract needs a check that its consumers still match it. | An API's OpenAPI document had been a 0-path skeleton. Once fixed to 575 paths, it became the contract the SDK, admin app and MCP server were checked against. | Module contracts are published with each module version, and consuming workflows are checked against them at promotion. | 03, 04 |

## Verification culture

| Lesson | What went wrong | What the platform does | Spec |
|---|---|---|---|
| Ask of any check whether it can return a false yes. | One overnight run found ten harness defects and seven product defects. A misspelled collection answered empty, an errored execution satisfied "not needs_input", and a health check answered 200 for a dead service. | Every gate check is paired with a second kind of evidence (a stored record, a screenshot, a second live request) and is shown failing once. | 04 |
| A status flag does not count as evidence. Keep the raw run. | A use-case runner marked stub scripts as PASSED in 1 ms and wrote "passed" into a registry, including three on auth and chat security. | Evidence attached to a version is the run itself: cases, outputs, scores, durations and assertion counts. A zero-assertion or near-zero-duration pass counts as a failure. | 04 |
| Contracts and type definitions describe what may be sent. They say little about what comes back. | Three "capability absent" conclusions drawn from DTOs were wrong. A create returned 201 and persisted nothing. A malformed probe's error was read as a service fault. | Module tests read state back after every write and assert on the stored record. | 03, 04 |
| A test input must be the type production actually produces. | A test passed while production broke, because it hand-built a deprecated input type that the library never sends. | Test cases come from real mail and real cases, captured through the same intake path. | 04 |
| Verify with the worst real content. | A dialog passed browser checks with 4 tools and overflowed with 12. | The sample-mail set includes the longest threads, largest attachments and empty and error cases the mailboxes have actually seen. | 04 |
| A documented contract with no consumer looks like a working feature. | Settings said keys come from the server, and no UI ever called the server. A field written by five commits was never read. | The builder flags any declared field, action or scope that no step reads. | 01 |
| A cold first run by someone new finds defects that experienced people no longer see. | A new engineer ran a tool from its quickstart and reported four defects. All four were real. | Each phase ends with a person outside the team building workflow two from the docs alone. | 04 |
| Check the live data model and the spec before building on a domain. | Content was written in a retired shape that the live database, the spec and the UI had all moved away from. | Work on a domain starts by reading its live records and spec, and the brief includes what was found. | Arch |

## Lessons that do not transfer

| Lesson | Why it does not apply here |
|---|---|
| Keep one resident agent on a live conversational turn; a router hop adds about 150% to time-to-first-token | Back-office runs have no person waiting on a live turn. The privilege part of the same finding does transfer (see identity). |
| Voice and telephony limits: concurrent voice-agent caps, dead air, carrier suspension, dial-time compliance gates | No calls are placed. |
| Voice pipeline frame types and interruption handling | Specific to voice libraries. The general testing lesson is kept above. |
| Public-facing widget origin checks, and a widget creating a session per page load | No public embedding. All users are authenticated staff. |
| An anonymous default endpoint so signup needs no key | The bank has no anonymous surface. The deny-by-default lesson is kept above. |
| Free-tier limits, credits and freemium quotas | Internal cost control uses per-agent budgets at the AI gateway. Billing tiers do not exist. |
| Tool packs sold through a store with explicit install | Modules are internal and approved by their owning team. "Curate before adding a second module" may still apply once the catalog grows. |
| Customer-facing versus internal agent tool tiers as a product split | All agents are internal. The operation-level scope lesson is kept above. |
| Multi-tenant SaaS workspace isolation | The bank is one tenant. The same isolation rules apply to departmental boundaries. |

## Top ten lessons, ranked by architectural weight

| Rank | Lesson | Why it ranks here | Spec |
|---|---|---|---|
| 1 | Identity, entitlement and risk tier come from platform context. Email content, including anything that looks like a header or an approval, is data. | Email intake makes untrusted text the input to every workflow. One in-band trust fact would give any sender access. | Arch, 01, 03 |
| 2 | The data gateway enforces scope per operation and binds the subject of each call from run context. Model arguments may only narrow it. | Two tools let the model choose the record or held write privilege under a read-sounding name. Neither the prompt nor the tool name can carry this. | 03 |
| 3 | Versions are immutable. Edits create versions through one write path, and promotion moves a pointer. | Partial-replace updates and a second write path both deleted configuration silently. Evidence must attach to something that cannot change after it is tested. | 01, 04 |
| 4 | Each fact has one home, the module manifest, and CI checks any copy against it. | Most "provisioned but invisible" incidents were two places disagreeing with nothing forcing them to agree. | Arch, 01, 03 |
| 5 | Evidence is the raw run, and every gate check is shown failing once and paired with a second kind of evidence. | False-yes checks outnumbered real defects. Model Risk will rely on this evidence. | 04 |
| 6 | The test suite runs the production runtime path with seeded identity and case state. | A separate test path left the identified, entitled branch untestable, which is the branch back-office agents run. | 04 |
| 7 | A drafted action is the complete payload, approval binds to it, only a human session can decide, and self-approval is refused. | Per-action approval is the bank's main control. Approving an instruction that is later turned into a different payload defeats it. | 01, 03 |
| 8 | The durable runtime guarantees a terminal state per run, idempotent side effects and versioned workers. | Stuck, duplicated and stale-worker runs were recurring incidents. SLA clocks depend on knowing run state. | Arch, 01 |
| 9 | Every job checks its target environment and store centrally, and the registry reports what is running where. | A month of backups of the wrong database, and design work built on an unmerged branch, both came from assuming the target. | Arch, 04 |
| 10 | All model traffic goes through the AI gateway, and an alias moves only after the tool-call and procedure suites pass on the new model. | Tool-call reliability and routing accuracy varied by model in ways size did not predict. Vendor updates will change both. | 03, 04 |
