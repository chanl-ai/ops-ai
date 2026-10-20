# ADR-0012 Assurance: governance and testing as one system

Status: option, not decided. No ADR has been confirmed by the maintainers as of 2026-10-10; each one records the options, a scoring and a recommendation, and the build keeps a seam open so the choice can differ per enterprise deployment.

## Context

The platform has grown to five kinds of asset that run or shape model behaviour: workflows (`01`),
agents (`01` 4.5), skills (`11`), agent templates (`12`) and tool modules (`03`). Shared prompt text,
once a separate prompt block, is an always-on skill since 2026-10-08 (`11` 4.1).
Each arrived with its own answer to the same four questions: how a change becomes a version, who
approves it, how it is tested, and what a reviewer can read afterwards.

| Asset | Version and approval before this decision | Testing before this decision | Evidence |
|---|---|---|---|
| Workflow | Draft, publish request, maker-checker in Reviews (`01` 5.5) | Suite of sample mails; gate by tier (`04`) | Sealed bundle on the version |
| Agent | Every save is a version; no approval; a workflow adopts it by pinning | Agent eval sets run on every save (`04` 5.10) | Summary on the version; read by the workflow bundle |
| Skill | Draft, `skill_publish` review, one or two approvers (`11` 5.1, 5.2) | Skill test cases, a subset of the agent checks; failing tests advisory at every tier | Test run and review on the version |
| Template | Submission to the platform team; review "later" (`12` 2) | Starter tests copied into new agents | None |
| Tool module | Security review per major; scope approvals on the module's Access tab (`03` 4.1) | Test bindings and stubs | Review record on the major |
| Model inventory | `model_validation` review in Reviews (`08` 4.3) | Reads agent and workflow eval results | Links to the workflow bundles |

Four pressures made the per-asset answers expensive:

| Pressure | What it costs |
|---|---|
| Six approval flows for one approver | A reviewer learns six screens and six rules for who may decide. Approvals for modules sit outside Reviews, so there are two inboxes (`03` 7, "so approvers have one queue (later)") |
| Six testing shapes | Trace assertions (tools called, order, cost) exist for agents and not for skills or workflows; a judge exists only as `rubric` on agent cases; multi-turn testing does not exist. Each new asset kind re-derives graders |
| Mistakes caught by people stay with the person | A rejected action or run is logged (`09` 4.3) and feeds the override rate (`08` 4.5), but nothing turns it into a test. The problem statement's "reviewer overrides feed the test set" was met for case corrections only (`04` 5.1.5) |
| Evidence assembled differently per asset | Model Risk reads a workflow bundle, an agent summary, a skill test run and a module review record. The inventory computes `lastEvalPassRate` from summaries instead of reading one record |

The question was whether to keep improving each asset's own testing and governance, or to make one
system that every asset kind uses.

## Options

| Option | What it is |
|---|---|
| A. Per-asset testing and governance, improved | Keep each spec's own lifecycle, tests and approvals. Add the missing pieces where each asset needs them: trace checks to skill tests, a judge to workflow rubrics, a module approval kind in Reviews |
| B. One shared Assurance system | One asset model (versions, draft, publish request, pins) for every kind; one Reviews queue whose approval properties come from the risk tier; one eval primitive (dataset, run, outcome and trace graders, calibrated judge, multi-turn simulation) for every kind; one evidence bundle shape that the model inventory reads as a view; a loop from every rejection to a draft test case |
| C. Adopt an external evaluation and governance product | An evaluation platform with datasets, LLM-as-judge, tracing and approval workflows (for example an open-source observability and evaluation suite, or an AI governance product) as the system of record for tests and approvals, with our registry publishing versions to it |

### Criteria

| Criterion | Why it matters here |
|---|---|
| One rule for who decides | Maker-checker and four-eyes must hold the same way for every change that can reach production, or the weakest asset kind is the way around the others |
| Evidence Model Risk can read once | Decision 2 of the problem statement: Model Risk accepts evidence on a version. One record per version beats four records to reconcile |
| Tests follow mistakes | The problem statement requires reviewer overrides to feed the test set. A loop that works only for case corrections leaves rejected runs and actions untested |
| Depth of testing per asset | Trace graders, judges with measured agreement and multi-turn simulation are needed for agents; skills and workflows need the same when they carry the same risk |
| Production path | design lessons: a test input must be the type production produces and the run must go through the production path. An external runner cannot drive the interpreter with seeded identity and case state |
| Throughput for many workflows | The marginal effort of workflow N (`../overview.md`, throughput). Datasets, judges, personas and libraries written once should serve every asset |
| Cost of the change | Specs and the console mock already exist per asset; unifying them changes `01` 4.5 (agent versions), ADR-0011 (block approval), `03` 7 (module approvals) and `12` 2 (template review) |

### Scores (1 poor to 5 good)

| Criterion | Weight | A | B | C |
|---|---|---|---|---|
| One rule for who decides | 20 | 2 | 5 | 3 |
| Evidence Model Risk can read once | 20 | 2 | 5 | 2 |
| Tests follow mistakes | 15 | 2 | 5 | 3 |
| Depth of testing per asset | 15 | 3 | 5 | 4 |
| Production path | 15 | 5 | 5 | 1 |
| Throughput for many workflows | 10 | 2 | 4 | 4 |
| Cost of the change | 5 | 5 | 2 | 2 |
| **Weighted total** | 100 | **2.80** | **4.85** | **2.70** |

Notes on the scores:

- **A** keeps every existing spec intact and scores on cost. It loses on the governance criteria
  because agents have no approval at all: a workflow adopts whatever agent version its editor pins,
  and the only check is the workflow's own gate. Adding a judge, trace checks and a loop to each
  asset separately means writing each three times and keeping them aligned by hand.
- **B** makes the five asset kinds instances of one model. Agents gain a publish request, which is
  the one change with a cost for editors (`04` open question 10). The graders, judge, simulation
  engine, libraries and evidence shape are written once. The inventory stops computing its own
  numbers and reads bundles. The cost is a round of edits to `01`, `03`, `11`, `12` and ADR-0011,
  listed under Consequences.
- **C** would bring datasets, judges and tracing in one product, and some products include review
  flows. It scores lowest on the production path: none of the candidates drives our interpreter
  with seeded identity and case state, so the tests would run a different path from production,
  which the design lessons rule out. Approvals held outside the registry split maker-checker across
  two systems, and the evidence Model Risk needs would live in two stores. Which products can run
  fully inside the bank with the needed audit trail was **not assessed** (**unverified**). ADR-0007
  already keeps such products at the edges: offline red-team generation, judge scorers, tracing.

## Decision

| Item | Choice |
|---|---|
| Asset model | Agents, skills, workflows, agent templates, tool modules and judges share one lifecycle: versions, one draft, a publish request, pins by version. Drafts and edit classes are `01` 5.4; `04` 4.9 maps each kind |
| Agents | Saves create draft versions; a review of kind `agent_publish` publishes one; workflows pin published versions only. This extends `01` 4.5 |
| Queue | Reviews holds every decision: paused runs, publish requests of every kind, tool reviews and scope approvals, template submissions, skill publishes, model validations, pairwise verdicts. `case_action` stays in the case (`01` 5.8) |
| Approval strictness | Maker-checker and four-eyes are properties of the review kind, set by the risk tier as gate data: one approver at `low` and `medium`, two with the second from the second line at `high` and `critical` (`04` 5.12) |
| Eval primitive | A dataset of cases; a run of an asset version against it, paired with the live version, on the production runtime in test mode; graders on the outcome and on the trace (tools called, order, arguments, step count, cost); a judge for criteria that need reading; multi-turn persona simulation scored by a scorecard (`04` 4.1–4.3, 4.12) |
| Judge | A versioned asset with a calibration set of human-labelled cases. Agreement per criterion is measured on every judge publish and shown beside every verdict; an uncalibrated verdict is advisory at every tier (`04` 4.11, 5.13) |
| Evidence | One bundle shape per version of any asset kind, sealed at approval, immutable, with later facts appended. Model Risk, Audit and the change board read it; the model inventory (`08`) is a view over it and stores no quality numbers of its own (`04` 4.6, 5.16) |
| Loop | A rejection or edit in Reviews creates a proposed case in the producing asset's dataset. Online scoring of live runs and synthetic generation from documents add proposed cases later. Pairwise candidate-against-live comparison with a human verdict feeds judge calibration. Only the maintainers activates a case (`04` 5.15) |
| Gate | The tier table of `04` 5.5 stands, extended to every pinned asset (S14–S16), with evidence export at seal for `high` and above (S17) and judge results advisory until calibrated (S18) |
| Console | One Assurance page (suites, runs, gates, evidence, judges, model inventory) and an Evals tab on agents, skills and workflows; `/model-risk` stays as an alias |
| External products | None as the system of record. Offline generation, judge model calls and tracing may use adopted tools at the edges (ADR-0007) |

## Consequences

| Consequence | Detail |
|---|---|
| Agent editors wait for an approver | A re-test edit on an agent at `low` needs one other person before a workflow can pin it. Measured in phase 1; `04` open question 10 asks whether that is acceptable or an auto-approval at `low` is needed |
| `01` 4.5 changes | Agent versions gain a `state`; "every save creates a version" becomes "every save creates a draft version"; `01` 5.5.11 stands (agent saves never change a published workflow) |
| ADR-0011 changes | Prompt blocks are folded into skills (2026-10-08): shared text is an always-on skill and publishes through `skill_publish` with its own tests. ADR-0011 is superseded |
| `03` 7 and `12` 2 move earlier | Module reviews and scope approvals are decided in Reviews in phase 1 (listed as later in `03`); template review moves from later to phase 1 as `template_publish` |
| `11` 5.2.2 changes | Failing skill tests are advisory at `low` only; at `medium` and above they block, as for agents (`11` Q3 is answered) |
| `08` stores less | `lastEvalPassRate`, `passRateByVersion`, `evidence[]`, `bundles[]` and `overrideRate30d` are read from Assurance records at request time; `08` 4.5 and 4.6 become read models |
| One grader vocabulary | `04` 4.2 is the only list of graders; `11` 4.4 and the agent check types in the mock map to it |
| Judges, personas, scenarios and scorecards are new assets | They need owners, versions and a place in the console; the platform team with Model Risk owns them in phase 1 |
| More reviews in one queue | Reviews must filter and sort well, or the queue becomes the bottleneck. `04` 9 sets the list target; bulk decide stays limited to low-risk non-publish kinds |
| A stricter day one | A workflow cannot pin an agent version that nobody reviewed. The lending servicing workflow's agents need one publish each before its first publish request |

### What would change this decision

- Review turnaround for agent publishes at `low` exceeds one business day in phase 1 and editors
  route around it by editing workflows instead. Then add auto-approval for re-test edits at `low`
  with the run as the approver's record, keeping maker-checker for re-approval edits.
- The bank already runs an evaluation or governance platform inside its perimeter with an audit
  trail Model Risk accepts. Then publish versions, runs and bundles to it read-only; the registry
  stays the source of truth and the gate still reads our runs.
- Judge calibration never reaches the bar for the criteria that matter (`04` open question 9).
  Then judges stay advisory and pairwise human verdicts become the scored path for those criteria.
- Simulation cost per conversation case makes `high`-tier repeats unaffordable. Then conversation
  cases run once with the transcript sampled for human review, and repeats apply to message cases
  only.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| One lifecycle and publish review per asset kind; Reviews with per-kind properties by tier; dataset, run, outcome and trace graders; judges with calibration and agreement shown; one persona per conversation case with an eight-persona library; rejection-to-case loop; pairwise verdicts; evidence bundle per version with export at `high`; inventory as a view; Assurance page | Online scoring of live runs; synthetic case generation from documents; adversarial multi-turn personas in the injection library; judge scoring thresholds per tier; department-owned judges and scorecards; auto-approval at `low` if measured turnaround requires it; preference-share gate step for pairwise runs |
