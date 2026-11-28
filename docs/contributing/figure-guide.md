# Figure guide

Status: current. Applies to every page on the Docs, Deploy and operate, Security and Reference tabs.

A figure replaces two to four paragraphs that explain a flow, a comparison, a set of options or a structure. It
carries the facts the paragraphs carried, so the page loses words and keeps every fact. A figure that only decorates,
or that repeats a paragraph left beside it, is cut.

## Pick the figure for the content

Every figure in the library, with its markdown and when to pick it over the others, is on [Figures](figures.md). Start
there; the rows below cover what the library does not draw.

| The text explains | Use | How to write it |
|---|---|---|
| A flow, screens, a lifecycle, a choice, options, a span of time, a request and its response | A library figure | `<!-- site: <kind> caption="..." -->` above a list or two code blocks ([Figures](figures.md)) |
| Steps a reader performs | Steps | `<!-- site: steps -->` above a numbered list |
| Options, roles or parts, three to six of them, each a link | Cards | `<!-- site: cards -->` above a table or list; the first cell or bold opening is the title |
| Status of several things | Badges inside a table | A cell starting with built, partial or planned |
| A screen as it ships | A framed screenshot | `![caption](https://opsai.chanl.ai/docs/media/name-light.png)` alone in a paragraph, light and dark variants as the page already does |
| A system's boxes and their links | The live architecture diagram | `![caption](https://opsai.chanl.ai/docs/diagrams/name.svg)` where `diagrams/name.yaml` exists |
| A data model | Mermaid `erDiagram` | A ```` ```mermaid caption="..." ```` block |
| A comparison across many attributes | A table, not a figure | Plain table |

A sequence or state that mermaid draws today moves to the library's sequence or state figure when its page is next
edited. Anything else stays prose. A carousel from the website is not used: the docs print, are searched by the
browser and are read at 390 wide.

## Where the library lives

All figures are one module, `apps/docs/src/components/figures`:

| Part | File |
|---|---|
| What each marker reads from the markdown below it, and the errors it raises | `apps/docs/src/components/figures/markdown.mjs` |
| The frame, caption, numbered pins, notes and path node every figure shares | `apps/docs/src/components/figures/parts.tsx` |
| The styles, from the theme variables only | `apps/docs/src/components/figures/figures.css` |
| One component per kind, exported from | `apps/docs/src/components/figures/index.ts` |

A new kind needs a parser in `markdown.mjs`, a component built from `parts.tsx`, its styles in `figures.css`, and a
section on [Figures](figures.md) with its markdown and when to use it. A component that needs its own colours or
spacing values is rejected in review. Add a kind only when a reader page needs it and no kind fits.

## How the website's patterns carry over

| Product website pattern | Docs equivalent |
|---|---|
| Feature cards: a title that carries its meaning, one line below | Cards: the title is the sentence a reader would say to a colleague |
| Three-step section | Steps |
| Persona and voice-agent carousels | Cards that stack; never a carousel |
| Problem section: the workaround, then the product's answer | Before and after |
| Section with a lead line, a visual, then proof | A one or two sentence lead, the figure, then the next heading |
| Feature cards that hold a live product widget | Widget: one panel beside the text; journey: each step shown as the screen it happens on |
| Whole product screens, scaled to fit, as "what you will see" | Preview: the console's sidebar and one page, one cropped panel on a phone, no tabs or rotation |
| Numbered callouts beside a product shot | Annotated screen pins and the journey's numbered path |

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

## Motion and focus

Motion is on transform and opacity only, and only where a figure is read once: the journey reveals its steps when it
scrolls into view (an 8px rise, 260ms, ease-out, 70ms apart). Nothing rotates or plays on its own. With reduced motion
the steps fade without moving; without JavaScript and in print they are simply there. Nothing in a figure takes focus:
drawn buttons and tabs are text, and a figure never scrolls inside itself.

## Caption and alt text

- The caption is one sentence that says what the figure shows and what to take from it. "How a version moves from draft
  to published" passes; "Diagram" and "Figure 1" fail.
- A figure's caption is also its accessible name, so it must make sense read alone. A screenshot's alt text is
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
| Before and after | The before-after figure, two labelled sides. A table with one row is never used for a pair |
| Paragraphs replaced | Two to four per figure |
| Library figures | The per-kind limits (steps, notes, participants, options) are checked by the build; see [Figures](figures.md) |
| Diagram direction | Top to bottom (`flowchart TD`) for any flow of more than 3 boxes. Left to right only for 3 boxes or fewer, drawn 420px wide or less |

Labels are in the reader's words. No file paths, service names, card ids, ports or customer names on a reader page.

## How a figure reads at 390 wide

A mermaid diagram shrinks to its frame (336px at 390 wide) down to 80% of its drawn size, so labels stay about 10px or
more, and scrolls sideways below that. Draw it to 420px or less, which means short labels and at most two boxes side by
side; a figure that scrolls sideways at 390 is a defect. Cards stack to one column, and every library figure has a phone layout of its own (rows instead of lanes, one panel
instead of a whole screen). The page itself never scrolls sideways. Check each changed page at 1440 and 390, in light and dark, before it is pushed.

## Sourcing

Take figures from the design pages (their mermaid blocks and
`.bp-figure` diagrams) and `docs/architecture`, and copy only what is true of the current release. Rewrite the labels
into reader language and drop internals. A design page's numbered explanation beside its diagram becomes the lead and
the caption.

## Check before pushing

1. The figure replaces paragraphs; the page has fewer words than before and no fact is lost.
2. It is a kind on [Figures](figures.md) or a row in the first table, written as its marker.
3. Caption, lead and reader-language labels are in place; no internals.
4. It reads at 390 wide in both themes.
5. `pnpm -C apps/docs build` passes.
