# ops-docs-write: write a user page for the docs site

Status: current. Proven by `make skills-proof`.

skill: ops-docs-write
description: Write a docs-site reader page to one of six page types.
targets: make docs-verify, pnpm -C apps/docs check:links, pnpm -C apps/docs build

## When to use it

A page someone reads to get something done with Ops AI, in the Docs, Security or Reference tab of the docs site. A
reader page says what the reader gets and how to do it. It never says where the code lives, how it was tested or what
is coming later. The page should still be true after a refactor.

## Voice

| Rule | In practice |
|---|---|
| Write to "you" | "You approve the write", not "the reviewer approves the write" |
| Say what the reader gets, then how | Open with the outcome; the steps and options follow |
| One name per thing | Use the name in the glossary, `docs/guide/glossary.md`. Add a missing term there first |
| Console paths copied from the screen | Bold, with `›` between parts, exactly as the glossary gives them: **Data Gateway › Apps** |
| Short sentences | Under 25 words. One idea each |
| Plain product language | Words a buyer would repeat. No keynote phrasing, no "simply", "just" or "easy" |
| Short table cells | 15 words at most. A longer explanation is a paragraph or a list |

## Page types

Pick one type before writing. A page that needs two types is two pages.

| Type | Must have | Never has |
|---|---|---|
| Landing | A one-sentence promise, a screenshot or a 10-line example, three routes | Feature tables, architecture |
| Quickstart | The outcome, prerequisites, at most 6 steps each ending in what you see, a run that uses an agent and an approval, 3 next links | Alternatives, flag tables, packaging caveats |
| Concept | A two-sentence definition, when to use it, one picture, a minimal example, links to its guide and reference | Command or error tables, status columns, internals |
| Guide | The goal, before you start, numbered steps on one path (console first, code in tabs), the result per step, troubleshooting | Re-explained concepts, a second way to do it |
| Integration | What you can do, connect steps, tools marked read or write, permissions asked for, sign-in errors, limits | Shared sign-in theory, plugin internals |
| Reference | Complete, and generated where possible: one entry per command, field or error, each with an example | Narrative, tutorials |

### Landing

```text
# <Product or area>

<One sentence: what you get.>

<A screenshot, or an example of 10 lines at most.>

## Where to go next
<!-- site: cards -->
- [<Route 1>](...): <who it is for>
- [<Route 2>](...): <who it is for>
- [<Route 3>](...): <who it is for>
```

### Quickstart

```text
# Quickstart

<The outcome: what runs at the end, with an agent and an approval in it.>

## Before you start
- <Prerequisite>

## Steps
<!-- site: steps -->
1. **<Action>.** <How.> You see <result>.
(6 steps at most)

## Next
<!-- site: cards -->
- [<Link 1>](...)
- [<Link 2>](...)
- [<Link 3>](...)
```

### Concept

```text
# <The thing>

<Definition in two sentences.>

## When to use it
<Two or three situations.>

<One picture: a mermaid diagram or a screenshot.>

## Example
<The smallest working instance, in the console first.>

## Next
- [<Its guide>](...)
- [<Its reference>](...)
```

### Guide

```text
# <The goal, as a task>

<What you will have at the end.>

## Before you start
- <What you need>

## Steps
<!-- site: steps -->
1. **<Action>.** <Console path and what to enter.> You see <result>.

## Troubleshooting
| You see | Do this |
|---|---|
```

### Integration

```text
# <App name>

## What you can do
## Connect
<!-- site: steps -->
1. ...
## Tools
| Tool | Read or write | What it does |
|---|---|---|
## Permissions it asks for
## Sign-in errors
| You see | Do this |
|---|---|
## Limits
```

### Reference

```text
# <Surface: CLI, API, MCP, a file format>

<One line on what this lists.>

## <Command, field or error>
<What it does, in one sentence.>
<One example.>
(one entry each, generated where possible)
```

## What stays off a reader page

`pnpm -C apps/docs check:links` fails on each of these; `apps/docs/scripts/check-public-pages.mjs` holds the rules.

| Leave out | Write instead |
|---|---|
| A Status line | Nothing. A reader page describes what works today |
| planned, upcoming, partial | Nothing. What is not built is listed only on the Feature status page |
| How the page was tested; branch, staging and release words | The behaviour the reader can rely on |
| Service, package and environment variable names (outside Reference) | The product noun the console uses, from the glossary |
| lease, journal, store layer, fencing, outbox | The outcome: "the run continues from the last saved step" |
| A second name for a thing, or a console path that differs from the glossary | The glossary's name and path |
| File paths, `file:line` references, ports, make targets | The public surface: the console, the `opsai` command, the API |
| Links into the repository or the Contributing tab | A link to another reader page |
| Test ids and use-case ids | Nothing |

## Example: before and after

Before (a source-code explanation):

> agents-service hosts `ops_hitl`; `may_read_thread` in `api/chat_threads.py:560` checks `can(caller, "chat",
> "read", team=...)` and the thread row's `team_id`. Port 8102.

After (a reader page):

> **Who can read a chat**
>
> A chat belongs to the team it was started in. Anyone on that team with the Chat permission can open it. Nobody
> outside the team can, even with a direct link.
>
> | Who | Can open the chat |
> |---|---|
> | The person who started it | Yes |
> | A team member with Chat | Yes |
> | Someone on another team | No |

## Steps

1. Pick the page type and the reader. Name the one job the page finishes.
2. Take every fact from the code or from a run of the product. Do not copy a claim from another page.
3. Write the opening first. If you cannot say what the reader gets in two sentences, the page does two jobs: split it.
4. Fill in the type's template. Use the glossary's names and console paths; add a missing term to the glossary first.
5. Run each example against a local stack and paste the real output, trimmed.
6. Use the site's components (`<!-- site: cards -->`, `<!-- site: steps -->`, callouts, mermaid, figures), listed in
   docs/README.md under "How the docs site shows a page".
7. Place the page in `SITE` in `apps/docs/src/lib/nav.mjs` and list it in `docs/README.md`. A page `SITE` does not
   name is not on the site.
8. Run `/ops-docs-review` on the page, apply its findings with `/ops-docs-edit`, then run the checks below.

```bash proof
make docs-verify
pnpm -C apps/docs check:links
```
