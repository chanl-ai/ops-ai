# Figure guide

Status: current. Applies to every page on the Docs, Deploy and operate, Security and Reference tabs.

A figure replaces two to four paragraphs that explain a flow, a comparison, a set of options or a structure. It
carries the facts the paragraphs carried, so the page loses words and keeps every fact. A figure that only decorates,
or that repeats a paragraph left beside it, is cut.

## Pick the figure for the content

| The text explains | Use | How to write it |
|---|---|---|
| A flow or sequence of steps, or who talks to whom | Mermaid flowchart or sequence diagram | A ```` ```mermaid caption="..." ```` block |
| A lifecycle with states (draft, review, published) | Mermaid flowchart with the states as boxes and the triggers on the arrows | Same block |
| Steps a reader performs | Steps | `<!-- site: steps -->` above a numbered list |
| Options, roles or parts, three to six of them | Cards | `<!-- site: cards -->` above a table or list; the first cell or bold opening is the title |
| A before and after, or with and without | A pair of two cards | `<!-- site: cards -->` above a two-item list: `- **Without Ops AI**: ...` and `- **With Ops AI**: ...` |
| Status of several things | Badges inside a table | A cell starting with built, partial or planned |
| A screen | A framed screenshot | `![caption](../media/name-light.png)` alone in a paragraph, light and dark variants as the page already does |
| A system's boxes and their links | The live architecture diagram | `![caption](../diagrams/name.svg)` where `diagrams/name.yaml` exists |
| A comparison across many attributes | A table, not a figure | Plain table |

Anything else stays prose. A carousel from the website is not used: the docs print, are searched by the browser and
are read at 390 wide, so options go in cards that stack.

## What exists, in the order to try it

| Need | Component | Where |
|---|---|---|
| Framed screenshot or wireframe | `OpsFigure` | `apps/docs/src/components/figure.tsx` |
| Flow, sequence, state | `OpsMermaid` (takes `caption`) | `apps/docs/src/components/mermaid.tsx` |
| Architecture boxes | `BoxDiagram` | `apps/docs/src/components/box-diagram.tsx`, drawn from `docs/diagrams/*.yaml` |
| Cards, pairs, option sets | `SummaryCards`, `SummaryCard` | `apps/docs/src/components/summary-cards.tsx` |
| Status | `StatusBadge` | `apps/docs/src/components/status-badge.tsx` |

A new component goes in `apps/docs/src/components`, is composed from these and the Fumadocs primitives, takes its
colours and spacing from the tokens below, and is mapped in `mdx.tsx` and `src/lib/remark-ops-ai.mjs` so authors write
plain markdown. A component that needs its own colours or spacing values is rejected in review.

## How the website's patterns carry over

| Product website pattern | Docs equivalent |
|---|---|
| Feature cards: a title that carries its meaning, one line below | Cards: the title is the sentence a reader would say to a colleague |
| Three-step section | Steps |
| Persona and voice-agent carousels | Cards that stack; never a carousel |
| Problem section: the workaround, then the product's answer | A with and without pair |
| Section with a lead line, a visual, then proof | A one or two sentence lead, the figure, then the next heading |

The wording follows the landing-copy rules: concrete nouns, a title that carries its meaning alone, no filler words,
and every claim a shipped feature. A card title that needs its body to decode is rewritten.

## Tokens

Figures take every colour from the CSS variables in `apps/docs/src/app/global.css`, which switch with the theme. No
figure contains a hex value.

| Use | Variable |
|---|---|
| Figure and card surface | `--ops-card`, border `--ops-line`, radius 10px, padding 10px (figure) or 12px 14px (card) |
| Text, secondary text | `--ops-fg`, `--ops-muted` |
| Emphasis, links, hover border | `--ops-accent`, `--ops-accent-soft` |
| Built, partial, planned, dropped | `--ops-new`, `--ops-warn`, `--ops-accent`, `--ops-drop` and their `-soft` backgrounds |
| Diagram colours | `--ops-mm-*`, set from the variables above, so one drawing serves both themes |
| Type | `--ops-font` at the page's 15px; captions 0.85rem in `--ops-muted`; code in `--ops-mono` |

## Caption and alt text

- The caption is one sentence that says what the figure shows and what to take from it. "How a version moves from draft
  to published" passes; "Diagram" and "Figure 1" fail.
- A mermaid caption is also the figure's accessible name, so it must make sense read alone. A screenshot's alt text is
  its caption.
- Each figure has a lead of one or two sentences before it that says why it is there. The lead does not repeat the
  caption.
- The figure holds the facts of the paragraphs it replaces. No paragraph after it restates it.

## Size

| Limit | Value |
|---|---|
| Figures per page | One to two. A third means the page is two pages |
| Boxes in a diagram | At most 8, labels at most 6 words |
| Cards in a set | Three to six |
| With and without pair | Two list items titled "Without ..." and "With ..."; the site mutes the first and accents the second. The title is the visible label, so a table with one row is never used for a pair |
| Paragraphs replaced | Two to four per figure |
| Diagram direction | Top to bottom (`flowchart TD`) for any flow of more than 3 boxes. Left to right only for 3 boxes or fewer, drawn 420px wide or less |

Labels are in the reader's words. No file paths, service names, card ids, ports or customer names on a reader page.

## How a figure reads at 390 wide

A mermaid diagram shrinks to its frame (336px at 390 wide) down to 80% of its drawn size, so labels stay about 10px or
more, and scrolls sideways below that. Draw it to 420px or less, which means short labels and at most two boxes side by
side; a figure that scrolls sideways at 390 is a defect. Cards stack to one column. The page itself
never scrolls sideways. Check each changed page at 1440 and 390, in light and dark, before it is pushed.

## Sourcing

Take figures from the design pages (their mermaid blocks and
`.bp-figure` diagrams) and `docs/architecture`, and copy only what is true of the current release. Rewrite the labels
into reader language and drop internals. A design page's numbered explanation beside its diagram becomes the lead and
the caption.

## Check before pushing

1. The figure replaces paragraphs; the page has fewer words than before and no fact is lost.
2. It is one of the types in the first table, built from an existing component.
3. Caption, lead and reader-language labels are in place; no internals.
4. It reads at 390 wide in both themes.
5. `pnpm -C apps/docs build` passes.
