# Agent scripts

The repeatable part of a review, a test audit, a browser walk and the finder scorecard, run before an agent in
`.claude/agents/` reads anything, so the agent spends its context on judgement. Every path, command and person they
use comes from `.claude/project-profile.md`; a flag overrides a row. How the agents use them: `CONTRIBUTING.md`,
"Agents and their scripts".

| Script | Make target | Writes |
|---|---|---|
| `review_context.py` | `make agent-review-context [BASE=origin/main]` | Diff stat, changed files by layer with the docs to read, tests added, new public surface, the leak, docs and lint checks |
| `test_audit.py` | `make agent-test-audit [BASE=] [DESIGN=] [PATHS=]` | Mutation score on the changed lines with each survivor, tests that cannot fail, duplicates, fixed waits, failure modes in the design with no test |
| `ui_walk.mjs` | `make agent-ui-walk ROUTES="/a /b" [AS=] [STATES=1]` | A screenshot per route, role and width, with page errors, failed requests, overflow and the mock states |
| `seed_canaries.py` | `make agent-canary`, `make agent-canary-score REPORT= KEY=` | A throwaway branch with planted bugs (committed past the hooks on purpose, since a planted bug is meant to fail them), the answer key kept apart, and a finder's recall and precision |
| `project_profile.py`, `project_profile.mjs` | - | The profile reader the scripts share |

Each script takes `--help` and `--self-test`; `make agent-scripts-test` runs every self-test. Output lands under
`.logs/agents/`, which git ignores. The make fragment is listed in `docs/architecture/make.md`.
