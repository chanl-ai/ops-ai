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

Claude Code also has agents for the stages of a change, in `.claude/agents/`, one narrow job each; see "Agents and
their scripts" below.

Decision records in `docs/architecture/decisions/` are binding on the specs. A spec that needs a
decision changed says so under "Open questions" and proposes a new or superseding ADR; it does not
re-decide the matter inline.

## Agents and their scripts

Each agent in `.claude/agents/` does one job and names the practice it follows (the sources are listed at the end of
`.claude/agent-rules.md`). The agents hold no fact about this repository: `.claude/agent-rules.md` holds the rules
every agent follows, `.claude/project-profile.md` holds every Ops AI fact they read (layers and their docs, tests and
how they run, the checks, the console's sign-in and roles, where designs live), and `.claude/workspace.local.md`
(ignored by git; template in `.claude/workspace.example.md`) holds what is true for one machine. To use the agents on
another repository, replace the profile.

| Stage | Agent | Job |
|---|---|---|
| Design | `ops-architect` | Owners, flows, data and decision records for a change; a fresh-eyes review of a design |
| Design | `ops-mock-designer` | Mocks from the console's existing components, every state, both widths |
| Test design | `ops-test-designer` | Failure modes first, one test per failure mode with what to revert to see it fail |
| Build | `ops-builder` | The code, tests and docs of one approved change, inside out |
| Test audit | `ops-test-auditor` | How effective the tests are: mutation score on the changed lines, tests that cannot fail, failure modes with no test |
| Browser test | `ops-browser-tester` | The few end-to-end paths through a headless browser as each role at both widths |
| UX review | `ops-ux-reviewer` | A mock or a built screen against the UI standard, the usability heuristics and WCAG 2.2 AA |
| Code review | `ops-code-reviewer` | One built branch against its design, the rules and its evidence; also security reviews |
| Triage | `ops-triage` | A reported bug reproduced read-only: cause, every place with the same problem, risk class, duplicates |

The repeatable part of each job is a script under `scripts/agents/`, run before the agent reads anything, with a
make target each (`make/agents.mk`). Every path and command the scripts use comes from the profile.

| Target | What it writes |
|---|---|
| `make agent-review-context [BASE=origin/main]` | `.logs/agents/review-context.md`: diff stat, changed files by layer with the docs to read, tests added, new routes, models, migrations and console routes, and the leak scan, public-path, docs and lint results on the changed files |
| `make agent-test-audit [BASE=] [DESIGN=docs/design/<area>/<topic>.md] [PATHS="…"]` | `.logs/agents/test-audit.md`: the mutation score on the changed lines (each fault runs only the tests that reach its line, found with coverage contexts; faults no test reaches are listed apart), every surviving fault with its file and line, tests that cannot fail (no assertion, always true, mock-only, duplicates), fixed waits, and the design's acceptance rows no test names |
| `make agent-ui-walk ROUTES="/a /b" [AS=admin,member] [WIDTHS=1440,390] [STATES=1]` | `.logs/agents/ui-walk/`: a screenshot per route, role and width, and a report of page errors, console errors, failed requests, sideways overflow, error text and unnamed controls; `STATES=1` adds the `?mock=slow\|error\|empty` variants |
| `make agent-canary [COUNT=6] [SEED=n]`, `make agent-canary-score REPORT= KEY=` | A throwaway worktree branch with five to eight known bugs planted from a catalogue (a role gate removed, a wrong plural, a fixed width that clips at 390, a raw id shown, a swallowed error, an empty state never reached, an unguarded write route, a tautological test, a team filter dropped); the answer key lands in `.logs/agents/canary-keys/`, outside the finder's reach; the planted commits skip the hooks (`--no-verify`) because a planted bug is meant to fail them, and the branch is deleted after scoring; the score lists caught, missed and false findings with recall and precision |
| `make agent-scripts-test` | Every script's own red and green cases (`--self-test`) |

A report from the test audit gives effectiveness, never counts: the mutation score on the changed lines with its
survivors, the failure modes with no test, and the tests worth deleting. Mutation testing with `mutmut` was tried
first and does not fit this tree as it stands: it copies a service's `src/` into `mutants/` and runs pytest there,
which loses the package's other modules, `alembic.ini` and the migrations unless every one is listed in `also_copy`,
and it mutates whole files rather than changed lines. The audit script mutates the changed lines in place, restores
the file after each fault, and runs only the tests that reached the line.

## Verify and the pre-commit hook

```bash
pnpm verify
```

`pnpm verify` type-checks the console and runs `apps/console/scripts/check-standards.mjs`, which
enforces the grep-provable rules in `apps/console/CLAUDE.md`. `pnpm install` in the main checkout copies
`.githooks/pre-commit` into `.git/hooks/`, and the hook runs `pnpm verify` on every commit. It runs on
what is being committed, not on the working tree: `scripts/verify-staged.sh` exports the commit's index
to a temporary directory, links `node_modules`, and runs the gates there with the checkout's own `.venv`,
which is never linked into the copy, so another builder's unfinished file in a shared tree does not block
your commit and nothing the hook runs reinstalls your Python packages. Fix the code rather than
bypassing the hook. `scripts/tests/test-verify-staged.sh` checks the hook end to end in a throwaway
clone.

Before calling a console change done, open every changed route in a browser and check it renders
without console errors, including the `?mock=slow`, `?mock=error` and `?mock=empty` states.

## Branches and pull requests

`main` is the trunk. It changes only through a pull request that CI has passed. Merging deploys staging; a tag
promotes a release.

CI (`.github/workflows/ci.yml`) runs only the jobs a change needs, chosen by `scripts/ci-plan.sh`, so most pull
requests skip some of them. The check that decides a merge is `ci-ok`: it always runs, waits for every other CI job,
and fails when any of them failed or was cancelled. A skipped job counts as passed. Wait for `ci-ok` to finish rather
than reading the other checks one by one; a red `ci-ok` names the failed job in its log. The secret scan (`scan`, in
`leak-scan.yml`) is a separate workflow and is also required.

| Step | Command |
|---|---|
| Start a change | `git switch -c <type>/<scope>-<change> origin/main`, for example `fix/tools-own-account-run` |
| Commit | `git commit` on your branch, as often as you like; the pre-commit hook runs the checks the staged files need |
| Open the PR | `git push -u origin HEAD`, then `gh pr create`; one change per PR, small enough to review in one sitting |
| Keep up with main | `git rebase origin/main` (or merge it) on your own branch |

One branch is one concern. A name says what changed, never who asked or which ticket. `git stash`, `git push --force`
and pushes straight to `main` are refused by the hooks.

### One stack, and reviewing a branch

A machine runs one stack, on the usual ports (console :3016), from one checkout of this repository. Work on your
branch in your checkout, and test with `make up`.

| Task | Command |
|---|---|
| Run your branch | `make up`: migrates, then restarts only the services whose code changed since they started |
| Try someone's branch | `make review BRANCH=<name>`: checks it out in the review worktree beside your checkout (`../ops-ai-review`, made on first use), installs, and runs the stack from there on the same ports. Your checkout and branch stay as they are; it refuses when the review worktree has uncommitted changes |
| Go back to your branch | `make up` in your checkout |
| Run tests | `make test PKG=packages/<name>` or `PKG=services/<name>` for one, `make test` for what changed since `origin/main`; `make usecase-test UC=<id>` for a use case |

Tests and use cases never run on the stack's database: each run makes its own throwaway database on the stack's
PostgreSQL, and a use case starts the services it needs on free ports, so neither needs a second stack. A branch made
before one stack per machine has make files that refuse to run from a worktree; merge `main` into it before
`make review`.

## Commit messages

Conventional commits: `type(scope): subject`.

| Part | Rule |
|---|---|
| Type | `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test` |
| Scope | The area changed, for example `console`, `specs`, `contracts` |
| Subject | Imperative, lowercase after the colon, no trailing period, under 72 characters; describes the change |
| Body | What was wrong before and why, then how the change was verified (the command run and its result). At most three lines and 320 characters (`scripts/commit-message-check.mjs`); no headings, tables or code blocks |
| Changelog | A feat or fix that changes `apps/` or `services/` names its What's new entry in a `Changelog: <topic>` trailer, for `changelog/<topic>.json` staged in the same commit |

## Everything here is public

This repository is public, and so is everything in it and around it: code, comments, docs, commit messages, branch
names, pull requests, issues, test fixtures, seed and sample data, mocks, screenshots, recorded logs and generated
files. Write each as if a customer, a regulator or a journalist reads it next to your name. The rules apply to people
and to coding agents alike.

| Rule | Detail |
|---|---|
| Tone | Plain, neutral and factual. State what the code does and why. No blame, sarcasm, insults, profanity or jokes at anyone's expense; describe the constraint instead. CI refuses the words listed under `tone` in `config/leak-patterns.txt` |
| Other parties | Say nothing unkind or unverified about customers, prospects, vendors, competitors or other projects. Name a third-party product only for a fact a reader needs, such as a supported version or a known bug with a link |
| Customers and people | No names of real customers, prospects, partners or people, and nothing that identifies them: no account names, org addresses, email addresses, ticket numbers or quotes from their messages. Use roles ("an admin", "the account owner") |
| Sample data | Fictional and generic, from several industries, never shaped after one real organisation. Domains use `example.com`, `example.org` or `.test`; phone numbers use reserved fictional ranges; no real-looking card, account or national id numbers. "Harbor & Pine Bank" is the console's fictional tenant |
| Screenshots and recordings | Taken on sample data only. No real accounts, email addresses, org addresses, tokens or browser tabs in view |
| Internal process | No internal tracker or story ids, internal tool names, session links, review chatter or "as discussed" references. A pull request links to public issues only |
| Secrets | Never a secret, token or private key, even an expired or test one that looks real. Use obvious placeholders (`<api-key>`) |
| Security | A weakness is described as fixed, with what changed. Exploit steps for an unfixed issue are reported privately through GitHub's private vulnerability reporting for this repository, never in a commit, issue or doc |
| Claims | Only claims the repository can back: a test, a command or a linked source. Mark anything unconfirmed as **unverified**. No promises about dates or customers |

`scripts/leak_scan.py` (run in CI by `.github/workflows/leak-scan.yml`) fails a change that adds home-directory paths,
tracker ids or trailers, session links or the tone words in `config/leak-patterns.txt`. The rest of this table is
checked in review.

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
| Sample organisations | Specs say "the organisation" or "a team", not one industry; older specs that say "the bank" change when next edited. See "Everything here is public" |
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
| `docs/usecases/` | Use case registry, one doc per use case under `<service>/`, their scripts under `<service>/scripts/` and their screenshots under `<service>/media/` |

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
| Names | A name or comment says what the thing is. Do not cite a card id, a board slice (`A2`, `W1`, `R7`) or a path into the private planning board. A public checkout does not have the board |
