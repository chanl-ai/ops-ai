---
name: ops-docs-write
description: Write a public docs page to the user-docs pattern.
allowed-tools: Bash(make *) Bash(uv run *) Bash(python3 *) Read Grep Glob
---

# ops-docs-write: write a user page for the docs site

<!-- Generated from `docs/guide/skills/ops-docs-write.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make docs-verify, pnpm -C apps/docs check:links, pnpm -C apps/docs build.

## When to use it

A page someone reads to get something done with Ops AI: a concept, a use-case guide, a deploy task, a security
question, or a reference landing page. Ops AI is self-hosted or hosted, so a user page states what the product does
and avoids where the code does it. The page should still be true after a refactor.

## The page pattern

Every user page follows this order. The style model is the FastMCP docs: short pages, one idea each, an example early.

| Part | What it holds | Length |
|---|---|---|
| Title | The task or the thing, in sentence case: "Ask a person before a write", not "HITL approvals subsystem" | 3-7 words |
| Opening | The problem this solves and when to reach for it. No paths, code spans or product-internal names | 2-3 sentences |
| Example | One thing the reader can run or click now, through a public surface: console steps, `opsai` CLI, SDK, HTTP API or MCP | One block, or one steps list |
| How it works | The behaviour the reader can rely on, as a short list or one diagram. Hosted and self-hosted differences stated once | 3-8 lines |
| Options | Settings, flags or variations as a table: name, what it does, default | A table |
| Limits | What it does not do yet, marked planned, and any limit a bank reviewer needs to know | 1-4 lines |
| Next | Two to four links to the next page a reader needs | Cards |

Page kinds and their example:

| Kind | Tab | Example is |
|---|---|---|
| Concept (agents, workflows, tools and apps, knowledge, approvals, cases, teams) | Docs | The smallest working instance, created in the console or with the CLI |
| Guide (a use case: card disputes, start the day from chat) | Docs | Steps from the problem to a result, with a console screenshot where a screen decides the step |
| Deploy task (install, upgrade, back up) | Deploy and operate | The commands an operator types, tabs for Compose, Kubernetes and hosted where they differ |
| Security answer (isolation, sign-in, audit, masking) | Security | The behaviour, the default, how an admin changes it, and the limit |
| Reference landing (SDK, CLI, MCP, API) | Reference | One authenticated call, then links into the generated reference |

## What stays off a user page

| Leave out | Write instead |
|---|---|
| File paths and `file:line` references | The behaviour: "A person outside the team cannot open the thread" |
| Module, package, class or table names | The product noun the console uses: Agent, Workflow, App, Human task |
| Ports, make targets, internal service names | The public surface: the console address, the `opsai` command, the API base URL |
| How the code is organised | One sentence on who decides, if the reader needs it: "Access is checked on the server for every request" |
| Test ids and use-case ids | Nothing. The Contributing tab links the test catalogue |

A link to a source file is allowed only on a Contributing page, or as a single "See the code" link at the end of a
Reference page.

## Example: before and after

Before (a source-code explanation):

> agents-service hosts `ops_hitl`; `may_read_thread` in `api/chat_threads.py:560` checks `can(caller, "chat",
> "read", team=...)` and the thread row's `team_id`. Port 8102.

After (a user page):

> **Who can read a chat**
>
> A chat belongs to the team it was started in. Anyone on that team with the Chat permission can open it; nobody
> outside the team can, even with a direct link. Admins can see every team's chats in Governance.
>
> | Who | Can open the chat |
> |---|---|
> | The person who started it | Yes |
> | A team member with Chat | Yes |
> | Someone on another team | No |

## Steps

1. Pick the kind from the table above and the tab it lives in. If the page explains code, it goes in Contributing.
2. Write the opening first. If you cannot say the problem in two sentences, the page does two jobs: split it.
3. Write the example and run it against a local stack or staging. Paste the real output, trimmed.
4. Check each behaviour claim against the code or a use-case run. Mark anything unbuilt as planned.
5. Use the site's components (`<!-- site: cards -->`, `<!-- site: steps -->`, callouts, mermaid, figures), listed in
   docs/README.md under "How the docs site shows a page".
6. Place the page in `apps/docs/src/lib/nav.mjs` and list it in `docs/README.md`.
7. Run `/ops-docs-review` on the page, apply its findings with `/ops-docs-edit`, then run the checks below.

```bash proof
make docs-verify
pnpm -C apps/docs check:links
```
