# Contributing

Status: current.

## Before you start

| Change | Read |
|---|---|
| Console code | `apps/console/CLAUDE.md` (layers, components, states, copy) and `docs/ui/page-plan.md` |
| A spec or decision | `docs/README.md`, `docs/background/problem-statement.md`, `docs/architecture/overview.md` and the ADRs |
| Backend design | `docs/backend/overview.md` |

Decision records in `docs/architecture/decisions/` are binding on the specs. A spec that needs a
decision changed says so under "Open questions" and proposes a new or superseding ADR; it does not
re-decide the matter inline.

## Verify and the pre-commit hook

```bash
pnpm verify
```

`pnpm verify` type-checks the console and runs `apps/console/scripts/check-standards.mjs`, which
enforces the grep-provable rules in `apps/console/CLAUDE.md`. `pnpm install` copies
`.githooks/pre-commit` into `.git/hooks/`, and the hook runs `pnpm verify` on every commit. Fix the
code rather than bypassing the hook.

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
| Headings | Sentence case |
| Tables | For anything enumerable; prose for reasoning only |
| Plain statements | State the fact and its consequence. No "X is a Y, not a Z" constructions, rhetorical questions or keynote phrasing |
| Filler | Do not use "simply", "just", "easy", "obviously" or "of course" |
| Code references | `path:line` or `path`, relative to the repo root |
| People | No personal names. Use roles ("the product owner", "the module owner") |
| The bank | "The bank" in specs; "Northfield Bank" is the fictional tenant in the console |
| Claims | Every "works" claim has evidence or a command the reader can run. Mark anything unconfirmed as **unverified** |
| File names | kebab-case; dated docs (plans, incident reviews) start `YYYY-MM-DD-`; living docs have no date |
| Length | What the content needs; no filler sections or repeated summaries |

## Code standards

Console rules live in `apps/console/CLAUDE.md` and are enforced in part by `pnpm verify`. Backend
standards (Python 3.12, uv, ruff, pyright, pytest, test levels) are in `docs/backend/overview.md`
and apply once backend code exists. In both: one test per failure mode, and each new test is seen
failing once before it is trusted.
