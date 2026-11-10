# Rules for every agent

Every agent in `.claude/agents/` reads this file first, then `.claude/project-profile.md` (every fact about this
repository: paths, layers, commands, conventions), then `.claude/workspace.local.md` if it exists (what is true for one
machine: where designs and evidence go, whether a tracker is used; copy `.claude/workspace.example.md` to start one).
This file holds what is true for an agent on any repository. Where a rule is owned elsewhere, the row says so and the
owner wins. Paths are relative to the repository root; in a git worktree, ignored files such as `workspace.local.md`
live in the main checkout (the first path printed by `git worktree list`).

## Which agent for which task

One agent per job. A stage names the agent that does it; the agent's file says what it reads, checks and reports.

| Stage | Task | Agent |
|---|---|---|
| Design | Architecture of a change: owners, flows, data, decision records, sequence diagrams | `ops-architect` |
| Design | Screens: mocks drawn from the real components, with every state, at both widths | `ops-mock-designer` |
| Design review | Fresh-eyes review of a design's architecture against the written rules | `ops-architect` (a session that did not write the design) |
| Design review | Review of the mocks and flows against the UX standard and the heuristics | `ops-ux-reviewer` |
| Test design | Failure modes first, one test per failure mode, each with what to revert to see it fail; the end-to-end paths | `ops-test-designer` |
| Build | Code, docs and tests of one approved design or fix, inside out | `ops-builder` |
| Test audit | How effective the tests are: mutation score on the changed lines, tests that cannot fail, failure modes with no test | `ops-test-auditor` |
| Browser test | The few end-to-end paths through a real browser, as each role, at both widths, with the states | `ops-browser-tester` |
| UX review | A built screen judged against the spec, the heuristics and WCAG 2.2 AA | `ops-ux-reviewer` |
| Code review | One built branch against its design, the rules and the evidence; a security review uses the same agent | `ops-code-reviewer` |
| Triage | A reported bug reproduced read-only: the cause (file:line), every place with the same problem, its risk class, and whether it is already open | `ops-triage` |

A change to a screen, an API contract, a data model or a flow across services goes through Design, Design review and
Test design before Build. A bug fix or a docs-only change goes to Build with the test designer's list of failure modes
in the brief. Every change goes through Test audit, Browser test (when a screen changed), UX review (when a screen
changed) and Code review before it merges.

## Scripts before thinking

Repeatable work is a script, run first, so the agent spends its context on judgement. Each takes `--help`; the
profile's "Commands an agent runs" table names the make targets.

| Script | Writes | Used by |
|---|---|---|
| `scripts/agents/review_context.py` | One bundle: diff stat, changed files by layer with the docs they map to, tests added or changed, new public surface, the leak scan and lint results | `ops-code-reviewer`, `ops-architect` in review, `ops-test-auditor` |
| `scripts/agents/test_audit.py` | Test effectiveness: mutation score on the changed lines with each surviving mutant, tests that cannot fail, duplicates, timing smells, failure modes in the design with no test | `ops-test-auditor`, `ops-test-designer` |
| `scripts/agents/ui_walk.mjs` | Screenshots of the given routes as each role at each width, with page errors, failed requests, overflow and the loading, error and empty states | `ops-browser-tester`, `ops-ux-reviewer`, `ops-mock-designer`, `ops-triage` |
| `scripts/agents/seed_canaries.py` | A throwaway worktree branch with known bugs planted from a catalogue, the answer key kept outside the finder's reach, and a score of a finder's report against it (caught, missed, false) | the finder scorecard for `ops-triage`, `ops-code-reviewer`, `ops-ux-reviewer` and `ops-test-auditor` |

## Working

| Rule | Owned by |
|---|---|
| Read the brief, the rules, the profile and the workspace file before any other file; then the documents the profile maps to the files the task names, and nothing else until a finding needs it | here |
| Keep each tool call under 2 minutes; run tests, builds and walks in the background and poll | here |
| Before adding any shared part, list what already does that job (file:line) and reuse it; a second owner needs a stated reason | the project's architecture rules (profile) |
| Work on your own branch from the trunk; commit after each slice that passes its own tests; one concern per branch and per commit | the project's contributing guide (profile "Conventions") |
| No `git stash`, hard resets, `git clean`, `--no-verify`, force pushes or pushes to the trunk | the project's hooks (profile "Conventions") |
| One stack per machine: tests and use cases make their own database and services, so they need no stack; never start a second stack; restart or switch the stack only if the workspace allows it | the project's run rules (profile "Console", "Tests") |
| Open a pull request only when the person who briefed you says so; push the branch | here |
| Stop processes by pid only; use a headless browser, never a person's own browser | here |
| Never print secrets or `.env` files; read single keys by name; never type a live secret into a field | here |
| Model calls in tests are scripted; real calls are capped by the project's rule | profile "Tests" |
| An agent that reviews, audits or tests does not change product code; it reports, with file:line | here |
| Tell the reader what to do, with the reason, in plain words; no narration of how the result was reached | here |

## Fixing a bug: cause first, once

`ops-triage` finds the cause and `ops-builder` fixes it; both follow these rows.

| Rule | Detail |
|---|---|
| Root cause first | Name the cause (file:line) with a confidence score from 0 to 100 percent and the evidence behind it: what was reproduced, which log line or test showed it, what else was ruled out |
| Fix the cause once, at the lowest shared layer that owns it | A package, the service kit, a shared hook or component, or a policy default, so every place with the same problem is fixed by one change, and a test or check stops it coming back. Never a patch on one screen or one call site |
| Under 80 percent confidence, reproduce first | Try to show the failure in an isolated harness (a unit test, a use case, a scratch headless script). If it still cannot be shown, do not fix it: add a log line or probe at the suspected seam, mark the item "waiting for recurrence" with what the probe will show, and fix when it recurs |
| A fix that reopens scores nothing | The finder scorecard (`scripts/agents/seed_canaries.py`) counts a bug as caught only while its fix holds; a reopened bug is a miss |

## Everything you write is public

Code, comments, docs, commits, branches, pull requests, fixtures, sample data, mocks, screenshots and logs follow the
project's public-writing rules (`CONTRIBUTING.md` "Everything here is public" here): plain tone, no real people or
organisations, fictional sample data from several industries, no internal trackers or session links, no secrets, and
only claims the repository can back.

## Done means

| Layer | Proof |
|---|---|
| api, sdk, cli, ui | The change's use cases pass at each layer they cover, run through the project's use-case command |
| Screens | Headless screenshots as each role the profile lists at both widths, including the empty, loading and error states, saved in the evidence folder |
| Tests | The suites of every package changed, with each new test seen failing once and that failure stated; the test audit's mutation score on the changed lines reported with its survivors |
| Docs | README and `docs/` updated in the same change; every new doc listed in the docs index |

A report states what ran and what it printed, per layer, and names anything not run. A passing typecheck alone is not
done. A count of passing tests is not evidence of effectiveness; the audit is.

## What a review reads

Every finding names the rule or document behind it and the code (file:line), ranked blocking, should or nice. A finding
no written rule covers is listed apart, so a rule can be added. The documents per area are in the profile ("Layers"
and "Designs, specs and decisions").

## Task tracker

When the workspace names a tracker, record evidence, hand back and give review verdicts the way its "Tracker" row
says. With no tracker, the report to the person who briefed you is the record.

## Sources

The practices in the agents come from these, read while writing them. Each agent cites the ones it follows.

| Source | Used for |
|---|---|
| Claude Code docs, "Create custom subagents" (code.claude.com/docs/en/sub-agents) | One narrow job per agent, short descriptions, detail in the body, tool allowlists |
| Claude docs, "Prompting best practices" (platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices) | Clear instructions with the reason behind them, what to do rather than what not to do, parallel tool calls |
| Google Engineering Practices, "What to look for in a code review" and "The standard of code review" (google.github.io/eng-practices/review/reviewer/) | The code review checklist; approve when the change improves code health; principles over opinions |
| Stryker Mutator docs, "Mutant states and metrics" (stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/) | Killed, survived, no coverage, timeout; mutation score = detected / valid |
| mutmut documentation (mutmut.readthedocs.io) | How a Python mutation run is configured and scoped; the mutation operators used |
| Inozemtseva and Holmes, "Coverage is not strongly correlated with test suite effectiveness", ICSE 2014 | Coverage finds untested code; it is not a quality target; mutation score measures effectiveness |
| Test smell catalog (testsmells.org) | Assertion-free, tautological, duplicated, sleepy and mystery-guest tests |
| Playwright docs, "Best practices" (playwright.dev/docs/best-practices) | Isolated tests, user-facing locators, web-first assertions, no fixed waits, few critical paths, do not test third parties |
| Nielsen Norman Group, "10 usability heuristics" and "How to conduct a heuristic evaluation" (nngroup.com) | The ten heuristics; two passes; one problem per finding with its heuristic |
| W3C, "How to meet WCAG 2.2" (w3.org/WAI/WCAG22/quickref/) | The Level A and AA criteria a console must meet |
| C4 model (c4model.com) | Context, container and component diagrams with titled, labelled, legended elements |
| ADR GitHub organisation (adr.github.io) and the Nygard template | Title, status, context, decision, consequences; supersede, never rewrite |
| Mermaid docs, "Sequence diagrams" (mermaid.js.org/syntax/sequenceDiagram.html) | The notation for flows: participants, arrows, alt and loop blocks |
| PEP 257 (peps.python.org/pep-0257/) and the Google Python style guide, section 3.8 (google.github.io/styleguide/pyguide.html) | Docstrings: when one is required, the summary line, Args, Returns, Raises |
| TSDoc (tsdoc.org) | Doc comments on TypeScript: summary, `@param`, `@returns`, `@remarks`, `@throws` |
