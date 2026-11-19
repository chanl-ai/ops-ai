---
name: ops-docs-review
description: Review a docs page as its five readers; changes nothing.
allowed-tools: Bash(make *) Bash(uv run *) Bash(python3 *) Read Grep Glob
---

# ops-docs-review: review a docs page as its readers would

<!-- Generated from `docs/guide/skills/ops-docs-review.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make docs-verify, pnpm -C apps/docs check:links.

## When to use it

A page or section is written or rewritten and is about to be committed, or an existing section is being audited.
The reviewer did not write the page. It reads the page as published (the preview URL or `pnpm -C apps/docs dev`),
not only the markdown.

## The readers

| Reader | Asks | Fails the page when |
|---|---|---|
| New developer | Can I get from zero to a result from this page? | The example does not run, needs a step it does not show, or uses a command that is not on the public surface |
| Operator | Can I do this task on my install, hosted or self-hosted? | It assumes one deployment without saying so, or hides a step behind "configure as needed" |
| Bank reviewer | Can I trust this, and what are the limits? | A security or data claim has no default, no way to change it, or no stated limit; a planned feature reads as built |
| Technical writer | Does each sentence earn its place? | Filler, aphorisms ("X is a Y, not a Z"), Title Case headings, an opening with paths or code spans, two jobs on one page |
| Designer | Can I scan it in ten seconds? | A wall of prose where a table, steps or one diagram would do; the example sits below the fold; no "next" links |

Plus one check for every page in the Docs, Deploy and operate, Security and Reference tabs: it explains behaviour,
not source code. File paths, module names, ports, make targets and test ids on such a page are findings.

## Output

Numbered findings, most important first, at most 12 per page. Each one line:

`N. [reader] <page>:<line or heading> - <what is wrong> -> <the fix>`

Then one line: `verdict: ship | edit | rewrite`. Ship means no finding above writer level. Rewrite means the page does
the wrong job (a code tour in the Docs tab, two topics on one page).

## Example

Reviewing `docs/guide/approvals.md`:

```text
1. [new developer] approvals.md:## Try it - the example calls `make seed-approvals`, which a user does not have -> use the console: Governance > Policies > Ask before writes, then send a chat that writes
2. [bank reviewer] approvals.md:## How it works - "writes are held for approval" with no default -> state the default (writes run at once unless a team turns on Ask before writes) and who can change it
3. [operator] approvals.md:opening - assumes self-hosted ("set OPS_REVIEW_KEY") -> hosted installs set this for you; move the self-hosted step to Deploy and operate
4. [writer] approvals.md:12 - "Approvals are a safety net, not a bottleneck" -> "A person approves a held write from the Human tasks page or from chat"
5. [designer] approvals.md:## Options - five options in prose -> a table: option, what it does, default
6. [source code] approvals.md:40 - cites ops_hitl/approvals.py:88 -> delete; the behaviour sentence above it already says it
verdict: edit
```

## Steps

1. Read the page as published. Note the tab it is in and which reader it serves first.
2. Run the example yourself where it can be run (local stack or staging). A finding that the example fails includes
   the output.
3. Check one or two behaviour claims against the code. A wrong claim is the top finding.
4. Write the findings in the format above. Do not edit the page; hand the findings to `/ops-docs-edit`.

```bash proof
make docs-verify
pnpm -C apps/docs check:links
```
