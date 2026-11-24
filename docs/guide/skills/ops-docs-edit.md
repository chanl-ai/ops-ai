# ops-docs-edit: apply review findings and tighten a docs page

Status: current. Proven by `make skills-proof`.

skill: ops-docs-edit
description: Apply review findings to a docs page and tighten it.
targets: make docs-verify, pnpm -C apps/docs check:links, pnpm -C apps/docs build

## When to use it

A review returned `verdict: edit`, or a page is mostly right but reads as internal notes. A `verdict: rewrite` page
goes back to `/ops-docs-write` instead.

## Edits, with before and after

| Edit | Before | After |
|---|---|---|
| Code reference to behaviour | "`can()` in `ops_access/core.py` refuses the call" | "The server refuses the request and the person sees: You need the Chat permission on this team" |
| Internal name to product noun | "an `ops_hitl` work item" | "a human task" |
| Aphorism to statement | "Masking is a default, not an option" | "Masking is on for every team. A team admin can turn it off in Governance" |
| Filler out | "Simply run the following command to easily install" | "Install the command line:" |
| Prose list to table | "You can set the timeout, which defaults to 30s, and the retries, which default to 3..." | A table: setting, what it does, default |
| Procedure to steps | "First open Apps, then pick the app and after that press Turn on" | `<!-- site: steps -->` with one action per step |
| Deployment-specific to stated once | "Edit ops-ai.env and restart" in a concept page | Concept page: "An admin sets this"; Deploy page: the file and the restart, per deployment |
| Unbuilt as built | "Agents are served over MCP" | "Team tools are served over MCP. Agents over MCP are planned" |

## Rules while editing

- Keep the page's job. If an edit would add a second topic, link to the page that owns it.
- Every heading in sentence case. The opening stays free of paths and code spans.
- A claim you cannot check against the code or a run is cut, never softened with "should". A reader page does not
  say planned; what is not built is listed only on the Feature status page.
- Code blocks show only what a user types or sees: console steps, `opsai` commands, SDK calls, HTTP requests, output.
- Keep the page shorter than it was unless the review asked for something missing.

## Steps

1. Take the findings in order. Fix each one, or note in one line why it does not apply.
2. Make the editing pass with the table above over the whole page.
3. Run the checks below and open the page in `pnpm -C apps/docs dev` (http://localhost:3040/docs) to look at it.
4. Commit by path: `docs(<section>): <what changed for the reader>`.

```bash proof
make docs-verify
pnpm -C apps/docs check:links
```
