# ADR-0011 Prompt management

Status: superseded by ADR-0012 and spec 11: shared text is an always-on skill, 2026-10-08. Instructions staying on the agent version still holds; the prompt block entity below does not.

## Context

An agent's instructions are its prompt. Spec `01` 4.5 stores them on the agent version as ordered
fragments, and every change to them is a re-test edit (`01` 5.4): the suite runs before any workflow
adopts the new version, and the version's digest is what Model Risk validates (`08`). Three things put
pressure on that model as the number of workflows grows:

| Pressure | Example | What it costs today |
|---|---|---|
| The same wording is needed in many agents | The deposit-insurance disclosure, the collections disclosure, the personal data rule, the plain-language tone guide | Each agent holds its own copy. A wording change from Compliance is a hand edit in every agent, and nothing lists which agents hold the old text |
| Teams start from the same few agent shapes | Email triage, reply drafting, policy Q&A, case summaries | Each team writes the instructions from scratch, so quality depends on who wrote them |
| Prompt engineering is a skill most ops teams do not have | A servicing lead knows the procedure but not how to phrase it for a model | Instructions miss citation rules, mention tools the agent does not hold, or contradict themselves; the design lessons record each of these (the design lessons, "Prompting and model calls", "Tools, MCP and scoping") |

The question is whether prompts should leave the agent version and become a subsystem of their own,
and if so, whether to build it or adopt an external prompt registry.

## Options

| Option | What it is |
|---|---|
| A. Prompts stay inside agent and skill versions | No change. Reuse is copy and paste; templates and a generator help authoring only |
| B. A separate prompt library | Prompts become first-class records with versions, variables and shared partials. Agents and skills reference prompts or partials; the library has its own evals and approvals |
| B-min. Prompts stay in agent versions, plus a small shared prompt blocks library | Agent instructions remain the agent's own text. Only reusable partials (disclosures, tone guides, policy rules, formats) live in a library, versioned and referenced from instructions as `{{block:<slug>@<version>}}`, pinned by version |
| C. An external prompt registry behind our registry | Adopt a prompt management product, for example Langfuse prompt management (open-source core; ADR-0007 already lists Langfuse for tracing), MLflow Prompt Registry or Agenta, and have agents fetch prompts from it at run time or at publish |

### Criteria

| Criterion | Why it matters here |
|---|---|
| One source of truth per fact | The evidence for a version must be the exact text the model read. Two places that can each change the prompt make that harder to prove |
| Versioning and pinning | A workflow pins agent versions at publish (`01` 5.5). Anything the prompt pulls in must be pinned the same way, or production changes without a publish |
| Edit classes | Prompt changes are re-test edits. A path that changes the prompt without a save on the agent skips the suite and the gate |
| Evidence for Model Risk | The validator signs a digest (`08`). The digest has to cover every word, including shared text |
| Throughput for many workflows | The marginal effort of workflow N (`../overview.md`, throughput). Shared wording should be written once |
| Operational cost | Another service, store, access model and audit trail to run inside the bank |

### Scores (1 poor to 5 good)

| Criterion | Weight | A | B | B-min | C |
|---|---|---|---|---|---|
| One source of truth per fact | 20 | 3 | 3 | 5 | 1 |
| Versioning and pinning | 20 | 5 | 4 | 5 | 2 |
| Edit classes respected | 15 | 5 | 3 | 5 | 2 |
| Evidence for Model Risk | 15 | 5 | 4 | 5 | 2 |
| Throughput for many workflows | 20 | 2 | 5 | 4 | 4 |
| Operational cost | 10 | 5 | 2 | 4 | 2 |
| **Weighted total** | 100 | **4.00** | **3.65** | **4.70** | **2.20** |

Notes on the scores:

- **A** scores 3 on one source of truth because the same disclosure exists in many copies that drift.
  It loses most on throughput: every disclosure change is N hand edits with no list of where they are.
- **B** makes the prompt a second versioned object next to the agent version. An agent version would
  pin a prompt version, so a reviewer needs both to know what the model read, and "a re-test edit to
  the agent" becomes "a re-test edit to the agent or to any prompt it pins". Its own evals duplicate
  the agent suites, which are the only place a prompt can be tested in context (`04`). It wins on
  throughput but adds a full subsystem the first workflows do not need.
- **B-min** keeps the agent's own instructions on the agent version. Shared text is referenced by an
  explicit pinned version, so the agent version's digest covers the block text through the pin, and a
  new block version reaches an agent only when someone re-pins and saves it, which is a re-test edit
  with the normal suite and gate. "Used by" on each block gives Compliance the list of agents that
  are behind. It loses one point on throughput because a block change still needs one save per agent;
  a later bulk re-pin removes most of that effort.
- **C** scores lowest on the bank's controls. External registries are built around labels such as
  `production` that move between versions; fetching by label at run time changes production without a
  publish, and fetching by version at publish copies the text back into our version anyway. The
  registry would hold prompt text the bank must also hold as evidence, so there are two stores and two
  access models for the same words. It would help with throughput and with prompt-level analytics,
  which ADR-0007 already covers through tracing. Which of these products can run fully inside the bank
  with the needed audit trail was **not assessed** (**unverified**).

## Decision

| Item | Choice |
|---|---|
| Where an agent's instructions live | On the agent version, as today (`01` 4.5). Skills keep their instructions on the skill version (`11`) |
| Shared partials | A prompt blocks library: `PromptBlock` with an owner team, a kind (disclosure, tone, policy, format), immutable versions and the variables its text uses |
| Reference syntax | `{{block:<slug>@<version>}}` inside instructions. Always pinned; there is no "latest" reference |
| Effect of a block publish | None on any agent. Agents show "v_n_ available"; adopting it is a re-pin in the agent's instructions and a save, which is a re-test edit |
| What the digest covers | The agent version's expanded instructions: its own text with each pinned block version expanded in place. The evidence bundle lists each block and version |
| Who publishes a block | The owning team requests it, and a review of kind `block_publish` in Reviews publishes it with one approver from the owning team who is not the author. A `disclosure` block at `high` tier or above needs a second approver from the second line (ADR-0012; `04` 5.11.3, 5.12.2). Blocks still have no dataset of their own; the review shows the agents and skills that pin the block and the latest run of each |
| Templates | Agent templates (spec `12` §4.1) copy instructions, guardrails and starter tests into a new agent at creation. They are not referenced afterwards and are not part of prompt management |
| Authoring help | The prompt generator writes plain instructions into the agent draft through the AI gateway (ADR-0008); it creates nothing on its own. Its lint runs against the agent's real grants, knowledge and variables |
| External registry | None in phase 1. Prompt-level analytics come from tracing (ADR-0007) |

The minimum in the console mock: Agent Studio → Prompt blocks (list, create, block page with versions
and used-by), Insert block on the agent's Instructions field and in the template wizard, block
selection in the generator's Compliance step, and the referenced blocks shown under the instructions
with "Use v_n_" when a newer version exists. Spec: [agent guardrails and skills](../agent-guardrails.md).

## Consequences

| Consequence | Detail |
|---|---|
| Compliance wording has one owner and one list of users | A disclosure change is one block version plus a re-pin per agent, each tested; the block page lists who is behind |
| Prompts stay testable only in context | Blocks have no suites of their own; the agent suites that pin them are the tests. A block change is as safe as the weakest suite of the agents that adopt it |
| Every adoption is an agent save | Many agents behind a block means many saves until a bulk re-pin exists (later) |
| The runtime expands references before the model call | Expansion is part of the compiler that builds the agent version's prompt. Stable blocks sit with the stable prompt, so prefix caching still applies (design lessons, "Prompting and model calls") |
| A deleted or unknown block blocks the save | The server refuses to save instructions that reference a block or version that does not exist (422) |

### What would change this decision

- More than about 30 agents pin the same block and re-pin saves become the bottleneck. Then add bulk
  re-pin: one action opens a draft on each agent behind, runs each suite, and lists the results.
- Teams want prompts shared at the level of whole agents, not partials. Then reconsider option B for
  that case only, keeping pins.
- The bank already runs a prompt registry with an audit trail it trusts. Then mirror published agent
  versions and blocks into it read-only for analytics; the version stays the source of truth.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Blocks library, pinned references, used-by, publish through a `block_publish` review (ADR-0012); agent templates as data, published through a `template_publish` review (ADR-0012); the generator and its lint; variables list | Bulk re-pin with suite results; block references inside skills; mirroring into an external registry |
