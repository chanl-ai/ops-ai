---
name: ops-fix-the-class
description: Before committing a fix, find every other place with the same fault, fix them all once in the layer that owns the job, add a check that stops it coming back, and state the sweep in a Siblings trailer. Use for every fix commit and whenever QA, a review or a walk reports a defect.
agent: agent
---

# ops-fix-the-class: fix every place with the same fault before committing

<!-- Generated from `docs/guide/skills/ops-fix-the-class.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make verify, node scripts/commit-message-check.mjs.

## When to use it

A fix is ready to commit, or a defect has just been found. A fix that changes one screen, one route or one call site
while the same fault stays elsewhere is a patch, and the commit check refuses a `fix` commit without a sweep.

## Steps

1. **Name the fault as a rule, not a symptom.** "A name longer than its column gives a 500" is a symptom; "request
   models allow a longer value than the column that stores it" is the rule. The rule is what you search for.
2. **Sweep for siblings.** Search the whole repo for the same shape: same field kind, same call, same pattern of code.
   Use Serena (`search_for_pattern`, `find_referencing_symbols`) or `git grep`, never a search of `/` or `~`. List every
   hit with file:line. Read `docs/architecture/engineering-standards.md` and the standards pages for a rule that already
   names this fault.
3. **Find the owner of the job.** Before writing a fix, list what already does this job (file:line). Fix it there: one
   shared validator, one paging helper, one picker, one error shape. A second owner needs a written reason.
4. **Fix the cause once.** Every sibling moves onto the owner in the same change. Do not add a guard at one call site,
   widen a limit, reword a message, or nudge a prompt in place of a rule. When the sweep is bigger than the card, say
   so on the card and size it; never ship the one-place patch because it is smaller.
5. **Make it unable to come back.** Add or extend a check that fails on the fault: a test through the public seam,
   a standards rule in `apps/console/scripts/check-standards.mjs`, a ratchet baseline, or a script in `make verify`.
   Watch it fail on the old code once.
6. **Say what you swept.** End the commit message with a `Siblings:` trailer:
   - `Siblings: 6 fixed via <owner>` names how many places and the one owner they now go through;
   - `Siblings: none, searched <pattern>` says what was searched when the fault had no other place.

## Examples

| Defect as reported | The rule | Patch (refused) | Class fix |
|---|---|---|---|
| A long agent name gives a 500 | Request models allow more than the column stores | Cap the agent name | One shared name field type, sized from the column, used by agents, guardrails, skills, form links and MCP links |
| A list shows only matches from the first page | Searching in the browser over a downloaded page | Fetch 500 rows | Send `search` to the API through the shared picker; the REUSE rule fails a new browser-side filter |
| A run list is slow at 5,000 runs | Paging in Python after loading every row | Raise the page size | One SQL paging helper; every list goes through it |
| A smoke script fails after its own invite | Callers renew sessions in different ways | Retry the request | Use the SDK's renewal path; no hand-written fetch |

## Proof

```bash proof
node scripts/commit-message-check.mjs --self-test
```
