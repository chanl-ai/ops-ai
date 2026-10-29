# Contributing

Status: current.

This page is for anyone changing Ops AI: how to run it, the checks a change must pass, and the standards the code and
docs follow. To run the stack first, follow the Quick start in `README.md`.

## Before you start

| Change | Read |
|---|---|
| Anything | `README.md` (Quick start), then `docs/README.md` for where each design lives |
| Console code | `apps/console/CLAUDE.md` (layers, components, states, copy) and `docs/console/page-plan.md` |
| A spec or decision | `docs/README.md`, `docs/background/problem-statement.md`, `docs/architecture/overview.md` and the ADRs |
| Backend design | `docs/architecture/README.md`, then `docs/architecture/service-map.md` |

Claude Code and GitHub Copilot come with skills for this repository: run the stack, install the sample team, add a
tool module or a workflow step type, write a use case, debug a service, work behind a mirror, pass the commit checks
and switch the database. In Claude Code they are `/ops-run`, `/ops-sample-team` and the rest; in Copilot Chat, the
prompts of the same names, with the rules in `.github/copilot-instructions.md`. Each is one page in
`docs/guide/skills/`; change the page, run `python3 scripts/agent_skills.py`, and `make skills-proof` runs every
skill's commands in a fresh devcontainer.

Decision records in `docs/architecture/decisions/` are binding on the specs. A spec that needs a
decision changed says so under "Open questions" and proposes a new or superseding ADR; it does not
re-decide the matter inline.

## Verify and the pre-commit hook

```bash
pnpm verify
```

`pnpm verify` type-checks the console and runs `apps/console/scripts/check-standards.mjs`, which
enforces the grep-provable rules in `apps/console/CLAUDE.md`. `pnpm install` copies
`.githooks/pre-commit` into `.git/hooks/`, and the hook runs `pnpm verify` on every commit. It runs on
what is being committed, not on the working tree: `scripts/verify-staged.sh` exports the commit's index
to a temporary directory, links `node_modules` and `.venv`, and runs the gates there, so another
builder's unfinished file in a shared tree does not block your commit. Fix the code rather than
bypassing the hook. `scripts/tests/test-verify-staged.sh` checks the hook end to end in a throwaway
clone.

Before calling a console change done, open every changed route in a browser and check it renders
without console errors, including the `?mock=slow`, `?mock=error` and `?mock=empty` states.

## Commit messages

Conventional commits: `type(scope): subject`.

| Part | Rule |
|---|---|
| Type | `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test` |
| Scope | The area changed, for example `console`, `specs`, `contracts` |
| Subject | Imperative, lowercase after the colon, no trailing period, under 72 characters; describes the change |
| Body | What was wrong before and why, then how the change was verified (the command run and its result). Six lines or fewer; no headings, tables or code blocks |

## Doc standards

### Every spec has this shape

Specs live under `docs/design/<area>/` and `docs/architecture/`, one topic-named file per spec; a spec number, where
there is one, lives in the title.

1. Status line and a one-paragraph summary.
2. Scope: in, out, and later phases.
3. Traceability: which problem-statement items (reasons, decisions, components, edit classes, knowledge requirements, flow steps) the spec serves, as a table.
4. Domain model: entities, fields, states and transitions (tables; mermaid state diagrams where states matter).
5. Behaviour: rules written as testable statements ("A version cannot promote while …").
6. API: operations the console's contract needs, with request and response fields, errors, idempotency and pagination. Each marked **phase 1** or **later**. APIs stay language-neutral (JSON Schema and OpenAPI).
7. UI mapping: each console route and dialog, the API it calls, and gaps between the console and the spec.
8. Security, audit and evidence: who may do what, what is logged, what becomes evidence on a version.
9. Non-functional: scale assumptions, latency targets, availability, retention.
10. Acceptance tests: end-to-end checks that prove phase 1 works. Each must be able to fail.
11. Open questions.

### Writing rules

| Rule | Detail |
|---|---|
| Status | Every doc states its status near the top: current, draft for review, or superseded by another file |
| Openings | The title, status line and first paragraph are for the reader, in plain words: no code span, path, service or package name, and no card id. File locations and proofs go lower, in a table or a hidden note. The docs site's link check enforces this on the Docs tab |
| Headings | Sentence case |
| Tables | For anything enumerable; prose for reasoning only |
| Plain statements | State the fact and its consequence. No "X is a Y, not a Z" constructions, rhetorical questions or keynote phrasing |
| Filler | Do not use "simply", "just", "easy", "obviously" or "of course" |
| Code references | `path:line` or `path`, relative to the repo root |
| People | No personal names. Use roles ("the product owner", "the module owner") |
| The bank | "The bank" in specs; "Harbor & Pine Bank" is the fictional tenant in the console |
| Claims | Every "works" claim has evidence or a command the reader can run. Mark anything unconfirmed as **unverified** |
| File names | kebab-case, named for the topic. No dates, numbers or sequence prefixes in file names; ids such as a spec number or ADR id go in the title, the status line says whether a doc is current or superseded, and git keeps the history |
| Content | Only what a reader acts on: decisions, rules, facts, gotchas and the evidence for them. No narrative of how a result was reached |
| Length | What the content needs; no filler sections or repeated summaries |

### Where docs live

Full documentation lives only under `docs/`, in a folder that maps to a part of the repo. A code folder carries a
short `README.md` (at most 40 lines: what it is, how to run it, links into `docs/`) and, where agents need different
rules, a `CLAUDE.md`. `node scripts/check-docs.mjs` enforces this.

| Folder | Holds |
|---|---|
| `docs/background/` | Problem statement |
| `docs/architecture/` | Architecture overview, service map, backend overview, decision records in `decisions/` |
| `docs/design/<area>/` | Designs by product area (workflows, tools, human tasks, cases, chat, data) with their wireframes and mocks in `images/`, and prior-art studies in `research/` |
| `docs/console/` | Console page plan and UI designs |
| `docs/services/<service>/` | One folder per service; the name matches a folder in `services/` |
| `docs/packages/<package>/` | One folder per package; the name matches a folder in `packages/` |
| `docs/sdk/` | The Python and TypeScript SDKs in `sdk/`, one guide per language |
| `docs/deploy/` | Runbooks for the VM, Compose and Kubernetes targets |
| `docs/plan/` | Plans, named for their topic |
| `docs/artifacts/` | Published HTML design artifacts |
| `docs/usecases/` | Use case registry, one doc per use case under `<service>/`, and their scripts under `<service>/scripts/` |

Every doc under `docs/` is listed in `docs/README.md`.

## Code standards

Console rules live in `apps/console/CLAUDE.md` and are enforced in part by `pnpm verify`. In both the console and
the backend: one test per failure mode, and each new test is seen failing once before it is trusted.

| Backend standard | Rule |
|---|---|
| Language and tooling | Python 3.12, one uv workspace at the root, ruff (lint and format), strict pyright, pytest |
| Layers | Services import packages, never each other's code; packages never import a service (`docs/architecture/service-map.md`). `services/agents-service/scripts/check_standards.py` enforces the layer order |
| Config | Settings are read once, from the environment, by `ops_service_kit.settings`; a bad value stops the process at start. No `.env` files |
| Fixtures | Only under a service's `tests/fixtures/` |
| Routes | Every route is authenticated, except health and the OpenAPI document |
| Model calls in tests | Scripted model only; real calls are capped at 10 per experiment unless a maintainer approves more |
| Gate | `make verify` before every commit |
