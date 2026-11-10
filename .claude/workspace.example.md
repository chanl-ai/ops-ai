# Workspace settings for Ops AI agents (example)

Copy this file to `.claude/workspace.local.md` in the main checkout and fill it in. Git ignores the copy. Every agent
in `.claude/agents/` reads it after `.claude/agent-rules.md`. Leave a line out to use the default.

| Setting | Value |
|---|---|
| Design folder (design pages and mocks) | `docs/design/` |
| Evidence folder (screenshots and walk results) | `docs/test-results/` |
| How to save to those folders | commit them on your branch |
| Shared stack agents must not restart or write to | none |
| UX specs for screen reviews | none beyond the console's components |
| Project rulebook | none |
| Plugins repository | `../ops-ai-plugins` |

## Extra rules for this workspace

None.
