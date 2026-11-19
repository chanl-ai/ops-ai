# Workspace settings for Ops AI agents (example)

Copy this file to `.claude/workspace.local.md` in the main checkout and fill it in. Git ignores the copy. Every agent
in `.claude/agents/` reads it after `.claude/agent-rules.md` and `.claude/project-profile.md`. A row left out uses its default.

| Setting | Default |
|---|---|
| Design folder | `docs/design/<area>/<topic>.md` in the "Every spec has this shape" form, mocks in `docs/design/<area>/images/`, listed in `docs/README.md` |
| Evidence folder | `docs/usecases/<service>/media/` |
| How designs and evidence are saved | committed on the agent's branch |
| May agents restart or switch the stack (`make up`, `make review`) | yes |
| UX specs for screen reviews | `apps/console/CLAUDE.md` and the shared components |
| Project rulebook | none |
| Plugins repository | none |
| Tracker | none: the report to the person who briefed you is the record |

## Extra rules for this workspace

None.
