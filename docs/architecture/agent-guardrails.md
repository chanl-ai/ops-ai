# Agent guardrails and skills

Status: in code 2026-10-16 (c-063). How an agent enforces the guardrails it pins and loads the skills it holds, and
which agent settings are not enforced yet. Parent page: [runtime.md](runtime.md). Use case: uc-085
(`docs/usecases/agents-service/agent-guardrails-blocked-topics.md`).

## The attachment model

A guardrail and a skill are each a versioned entity owned by a team, published through a review, and attached to an
agent version as a pin on one published version. A rule written once (no investment advice, owned by Compliance)
reaches every agent that pins it, and a change to it is reviewed once.

| | Guardrail | Skill |
|---|---|---|
| Store | `registry_guardrails`, `registry_guardrail_versions` (migration `0025_guardrails`) | `registry_skills`, `registry_skill_versions` (`0026_skills`) |
| Kinds | `blocked_topics {topics[], message, scopes?}` only | `on_match` (indexed, loaded with `load_skill`) or `always` (in every turn) |
| Edit | `PATCH /v1/guardrails/{id}` saves the next version as a draft | `PUT /v1/skills/{id}/draft` edits the newest draft, or opens the next version on a published one |
| Publish | `POST …/publish-requests`; request kind `guardrail`, ids `GRP-` | Same; kind `skill`, ids `SKP-` |
| Decide | `/v1/publish-requests/{id}/decision` or Reviews; not by whoever asked or saved; approved at once under the dev auto-approve setting | Same |
| Pin on the agent version | `guardrailPins[]` via `PATCH /v1/agents/{id}` | `skillPins[]` via `PUT /v1/agents/{id}/skills/{skillId}` |
| Pin refused (422) | Version not published, guardrail deprecated | Version not published, skill deprecated, agent lacks a tool or knowledge base the version names, over 12 skills |
| Delete refused (409) | While an agent's newest or published version pins it, or a published workflow's agent step carries it | Same |
| Console | `/guardrails` (create, edit, publish, deprecate, delete); the agent page's Guardrails section pins | `/skills`; the agent page's Skills section attaches |

The agent version snapshots each pinned version (topics, scopes and message, or body, guardrails and tokens), so the runtime
serves a pin with no lookup per turn. An agent edit that drops a tool or knowledge base a pinned skill names is refused
(`skill_needs_scope`). A pin, like any agent change, serves once the agent version is published; a v1 workflow keeps
the agent version it was published with until it is republished.

## The guardrail check (`packages/ops_agent_kernel/src/ops_agent_kernel/guard.py`)

| When | What runs | On a hit |
|---|---|---|
| Before the answer | One classification call on the person's message through the turn's model, with structured output whose `topic` is one of the pinned topics or `none` | The guardrail's message, stop reason `guardrail`; the answering model is never called |
| After the answer | The same call on the complete answer, with the topics of any skill loaded in the turn added | One correction by a tool-less agent, checked again; if it still hits or fails in any way, the guardrail's message |

### Topic scopes

Each blocked topic can carry a scope: what it covers and what it does not. It is stored in the version's `config`
JSON as `scopes: {topic: text}`, so it is versioned, reviewed and pinned with the topics; no migration was needed, and
a version without `scopes` keeps the shape and digest it had. The classifier prompt lists a scoped topic as
`- <topic>: <scope>` and a bare one as `- <topic>`, and its instructions say a message the scope excludes is `none`.
A scope whose topic a later version drops is dropped with it. API: `scopes` on `POST /v1/guardrails` and
`PATCH /v1/guardrails/{id}` (a patch replaces the map whole; omitted keeps it), `config.scopes` on every read. Console:
one optional "What <topic> covers" field per topic in the guardrail dialog.

Why: with bare labels, the real model (gpt-5.5) classified "My client lost her job. Compare Savings Plus and Money
Market for her." as investment advice and refused it. The seeded "No investment advice" scope reads: "Whether to buy,
sell or hold a security, or how to invest or allocate money in markets. Not: describing or comparing the bank's own
deposit accounts, savings products, rates, fees or eligibility." The seed is read once, so a stack seeded before this
change gets the scope by saving and publishing v2 and re-pinning it on `ag_advisor`.

Tests: `tests/unit/test_guardrails_kernel.py::test_a_topic_scope_pinned_on_the_agent_reaches_the_classifier_prompt`
(pin snapshot → catalog → kernel → prompt) and `tests/api/test_guardrails.py::test_a_topic_scope_is_versioned_and_reaches_the_served_definition`.
`make demo-walk` checks a pinned guardrail end to end on the sample team: a shares question is refused before any
answer.

An agent with a pinned guardrail, or a pinned skill that carries guardrails, never streams its answer: the stream shows
"Checking the answer…" and sends the checked answer, or the message, once. An agent with neither streams as before
and makes no classification call.

`TurnResult.guardrail` names the guardrail, version, topic and `when` (`before`, `after` or `corrected`), and the
chat message carries it, so the turn reads "Not answered: No investment advice v1 blocks investment advice".

## Fail closed

| Exit | Result |
|---|---|
| The classification call fails or returns a topic it was not given | Stop reason `guardrail_unavailable`, error code `guardrail_unavailable`, no answer |
| The correction call fails for any reason | The guardrail's message |
| A guarded turn ends early: tool or step limit, deadline, model error, any other exception, an approval stop | The unchecked text is dropped from the result and the stored message; only the notice or the error remains |

Withheld text (a withdrawn or rewritten answer, or the dropped text of an early exit) goes to the run's event log as a
`guardrail_withheld` event, for a reviewer; the conversation never shows it.

## Skills in a turn (`packages/ops_agent_kernel/src/ops_agent_kernel/skills.py`)

| Rule | Value |
|---|---|
| Index | Each on-match skill's slug and use-when line, in the system prompt after the instructions |
| Always-on bodies | Added after the agent's instructions in pin order, recorded as loaded with "Always on" |
| Loading | The `load_skill` built-in returns the pinned body; it is not charged to the tool-call budget |
| Caps | 2 on-match skills a turn and 6,000 tokens of on-match bodies a turn; a load past either is refused and the turn goes on. Always-on bodies have their own budget, 2,000 tokens per agent, checked at attach, so they never use the on-match room |
| Size | Name at most 200 characters, instructions at most 24,000; a version whose body is over its budget (6,000 on-match, 2,000 always-on) cannot be published, since it could never load |
| Approvals | A turn that pauses for an approval carries its loaded skills in the interrupt; the resumed turn keeps them loaded, their guardrails still check the answer, and the caps continue |
| Scope | A skill adds instructions and, while loaded, guardrails; it never adds a tool or knowledge base |
| Record | A `skill_loaded` run event per load and `TurnResult.skills`; the chat turn reads "Loaded skill X v1". The model's `matched` words are cut to one line of at most 200 characters before they are journalled |

## Seeds

`seed/guardrails.json` and `seed/skills.json` sit beside the agents seed and are read at start. A seeded entity is
created once, published at v1, and pinned on the agents it names as a new agent version: published at once in dev,
through an `agent_publish` review elsewhere, and never over a draft a person saved (the seed then waits). Seed skills
name no tools, because the start-up seed has no tenant to read the tool directory with.

## What is enforced and what is not

| Setting | Enforced | Where |
|---|---|---|
| Blocked topics (pinned guardrails) | Yes | The guardrail check above |
| A loaded skill's guardrail lines | Yes | Added to the after-check while loaded |
| Tool calls per turn (`maxToolCallsPerTurn`) | Yes | `AgentSettings.max_tool_calls` in the kernel |
| Redact personal data (`redactPii`) | No | Saved with the agent; the console marks it "Not enforced yet" |
| When unsure (`whenUnsure`) | No | Saved with the agent; marked "Not enforced yet" |
| The agent's own free-text `blockedTopics` list | No | Replaced in the console by pinned guardrails; the stored list is not read |

Not built: skill tests, resources, load counts per agent, generation, import and export (spec 11 sections 4.4, 4.5,
5.6, 5.7; the console's calls for them answer 501 against agents-service); an upgrade prompt for a newer guardrail
version on the agent page; guardrail kinds other than blocked topics; team scoping of guardrails and skills (the same
gap agents have).
