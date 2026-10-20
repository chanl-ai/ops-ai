# Console UI standards

Status: current. The standard a console change is reviewed against. `apps/console/CLAUDE.md` holds the layer rules and
the component table; `strategy.md` holds the rules for what gets built; this page says how a screen is put together
and how a reviewer checks it. Where they disagree, `apps/console/CLAUDE.md` wins and this page is corrected.

## Tokens

Colours, radius and type come from the CSS variables in `apps/console/src/app/globals.css`, through their Tailwind
names. No new variable is added without a contrast reason recorded here.

| Need | Use | Not |
|---|---|---|
| Text | `text-foreground`, `text-muted-foreground` | `text-gray-*`, `text-black`, `text-white` |
| Surfaces | `bg-background`, `bg-card`, `bg-muted`, `bg-popover`, `bg-accent` | `bg-white`, `bg-gray-*` |
| Lines | `border` (the `--border` default), `border-input` | `border-gray-*` |
| Healthy, done, passing | `text-success-text`, `bg-success/10`, `border-success/40` | `text-emerald-*`, `text-green-*`, `text-success` for text |
| Needs a person, waiting, overdue soon | `text-warning-text`, `bg-warning/10`, `border-warning/40` | `text-amber-*`, `bg-amber-*`, `text-warning` for text |
| Failed, refused, destructive | `text-destructive`, `bg-destructive/10` | `text-red-*` |
| Charts | `--chart-1` to `--chart-5`, read at render so both themes work | hex in a series config |
| Corners | `rounded-sm`, `rounded-md`, `rounded-lg` (from `--radius`) | `rounded-[7px]` |
| Numbers | `tabular-nums` on every count, amount, time and percentage | proportional digits in a column |

`--success-text` and `--warning-text` exist because the fills are too light for small text. Measured WCAG contrast:

| Token | On background | On card | On muted |
|---|---|---|---|
| `--warning` (fill), light | 2.2:1 | 2.3:1 | 2.0:1 |
| `--success` (fill), light | 3.5:1 | 3.7:1 | 3.3:1 |
| `--warning-text`, light, oklch(0.52 0.12 65) | 5.5:1 | 5.7:1 | 5.0:1 |
| `--success-text`, light, oklch(0.5 0.13 150) | 5.4:1 | 5.7:1 | 5.0:1 |
| `--destructive`, light | 4.6:1 | 4.8:1 | 4.2:1 |
| `--warning-text`, dark, oklch(0.82 0.13 80) | 10.8:1 | 10.2:1 | |
| `--success-text`, dark, oklch(0.78 0.15 150) | 10.1:1 | 9.6:1 | |

`text-destructive` on `bg-muted` is below 4.5:1, so destructive text sits on the background or card.

One meaning per hue: success is healthy, warning is waiting on a person, destructive is failed. An agent acting and a
check passing are different facts, so they do not share a colour; an agent action is shown with an icon and text.
Raw `#hex`, `rgb()` or `oklch()` in a component, and inline `style={{ color }}`, are refused. A width or height set
through `style` for data (a progress bar) is allowed.

The console has existing debt here: 31 files carry 195 raw palette classes (any Tailwind hue) or fixed `w-[Npx]` widths
(`text-amber-700`, `bg-sky-500`, `border-violet-500/40`, `text-red-600` lead). `check-standards` rule 14 holds each file
to its count in `apps/console/scripts/palette-baseline.json` and a file not listed to none, so `pnpm verify` refuses a
new one. A conversion lowers the count and runs `node scripts/check-standards.mjs --write-baseline` to lock it in.

One component per job: a table is the data table, a status is a badge from `components/status-badges.tsx`, and the chat
composer and message renderers live in `components/chat`. `check-standards` rule 16 fails a raw `<Table>`, a local
`*StatusBadge` or a composer or message renderer anywhere else. The files that already did so are listed per rule in
`apps/console/scripts/reuse-baseline.json`; the list only shrinks, because a listed file that is fixed fails until
`--write-baseline` takes it off, and that mode never adds one.

## Layout primitives

| Surface | Primitive | Where | The rule |
|---|---|---|---|
| Page header | `PageLayout` | `components/page-layout.tsx` | Icon, title, one-line description, actions on the right; record pages pass `backHref` |
| Sibling pages of one section | `TitleSwitcher` via `PageLayout switcher` | `components/shared/title-switcher.tsx` | Pages come from `sectionFor` in `lib/nav.ts`; no tab strip of sibling routes under the header |
| Route tabs inside one record or area | `RouteTabs` | `components/shared/route-tabs.tsx` | Each tab is a URL, so a reload or a shared link lands on it |
| List | `DataTableWithViews` + `DataTableColumnHeader` + `selectColumn` | `components/data-table-with-views.tsx` | Faceted filters with counts from the API, server pagination through `useListParams`, bulk actions in the selection bar |
| Create, edit, confirm | `DialogShell` (`sm`, `md`, `lg`) | `components/shared/dialog-shell.tsx` | Header and footer fixed, body scrolls inside `max-h-[85vh]`; too much content means a wider size or steps, never a taller dialog |
| Inspect a row without leaving | `DetailSheet` | `components/shared/detail-sheet.tsx` | Prev and next, `scrollKey`, an id in the URL (`?run=`) so it reopens on reload |
| Record page | `RecordLayout` + `AttributeCard` + `FieldRow` | `components/shared/record-layout.tsx` | Rail of attributes, tabbed main |
| Delete, bulk change | `DeleteDialog`, `BulkConfirmDialog`, `BulkFieldDialog` + `toastBulk` | `components/shared/` | Consequence stated; skipped items named with the reason |

## Compose, never hand-roll

Before writing markup for a surface, in this order:

1. Find how the console already builds it. An existing page is the strongest spec: a new list uses the list pages'
   `DataTableWithViews`, a new record uses `RecordLayout`.
2. Reuse `components/shared/` and the area's components.
3. Search the shadcn registry for a block or primitive and add it through `components/ui/`.
4. Only then compose primitives in a new `components/shared/` wrapper.

`components/ui/*` is not edited; wrap it in `components/shared/`. Refused in review: hand-built `<ul>`/`<li>` rows
for anything a table or list primitive does, bespoke chip `<span>`s (use `Badge` or a `status-badges`
component), custom CSS for spacing, focus rings, hover, dark mode, sorting or selection, and a clickable `<div>` (use a
`Button` or a row `onRowClick`; if a div must take a click it gets `select-none`, a role and keyboard handling).

## Designed states

Every surface that shows data has all four, reviewed with `?mock=slow`, `?mock=error` and `?mock=empty`.

| State | Built with | It must |
|---|---|---|
| Loading | `PageSkeleton` (stat cards and rows set to the page's real count) or `RecordSkeleton` | Match the layout it replaces, so nothing jumps when data arrives; a spinner alone is refused |
| Empty | `ListEmpty` or `EmptyState` | Say what fills the list and offer the action that fills it; a filtered empty says so and offers Clear filters |
| Error | `QueryError` with Try again | Keep whatever the person typed: a failed save leaves the dialog open with its fields and shows the error inline |
| Partial | The page's own rows | A list that loaded keeps showing while a refetch fails; the error appears as a toast, not a blank page |

## Responsive

The console works from a 375 px phone to a wide monitor with no horizontal page scroll.

| Rule | How |
|---|---|
| No fixed widths on layout | Flex and grid with `minmax(0, 1fr)`; `w-[210px]` style widths only on a control inside a toolbar, a menu or popover panel, or a rail (a `shrink-0` column such as the chat thread list), never on a content column or panel; the toolbar, menu and popover cases stay counted in the baseline because rule 14 cannot tell them apart |
| Text children can shrink | `min-w-0` on every flex or grid child that holds text, with `truncate` or `break-words` on the text |
| Side gutter | `PageLayout` gives `px-6`, `lg:px-8`; nested content does not add or remove it |
| Tables | `DataTableWithViews` scrolls inside its own container; secondary columns start hidden through `initialColumnVisibility` |
| Dialogs | Two-column bodies use `grid-cols-1 md:grid-cols-2` so they stack on a phone |

## Creating a record

Creating anything is one screen: a `DialogShell` `md` with a name and the one field the record cannot exist without.
Submitting saves a draft and opens the record page, which holds everything else tab by tab. A wizard, template or
import is a second button, and only once the record page works over a real API. Starting a run is the same shape: one
dialog with the input the workflow needs, then the run appears where runs are read (Cases).

## Copy

Product copy only: sentence case, buttons name the action, no "(s)" plurals (`plural()` in `lib/format.ts`), numbers
carry units, placeholders start with "e.g." and never look like real records, and no developer explanation on screen.

## Review checks

The five rules from `strategy.md` and the rules above, as checks a reviewer can run. `pnpm verify` already runs the
grep-provable ones in `apps/console/scripts/check-standards.mjs`.

| # | Check | How to run it | Fails when |
|---|---|---|---|
| 1 | Every field on the page comes from a call | For each value shown, find it in the hook's response type and that type in `docs/architecture/api.md` | A value exists only in `src/lib/api/mock/` |
| 2 | Calls go through the one client per area | `git diff --stat -- 'apps/console/src/lib/api/*-http.ts'` | A hand-written client grows without a note naming the SDK call that replaces it |
| 3 | No additions to stub areas | Diff touches platform, hitl, models, kb or files screens | A new page, tab, dialog or wizard step appears there |
| 4 | Create is one screen | Open the New button | The first screen asks for more than a name and one required field, or the only way in is a wizard |
| 5 | The page is proved | `make usecase-test UC=<id> LAYER=ui` | No ui use case names the page, or it prints a FAIL line |
| 6 | Tokens only | `pnpm verify` (rule 14 counts palette classes and px widths per file against the baseline); read the diff for hex colours | A file's count rises, a new file has one, or a changed line adds a hex colour |
| 7 | Composed, not hand-rolled | Read the diff for `<ul>`, `<li>`, styled `<span>` chips and `onClick` on a `div` | One of them does what a primitive does |
| 8 | States are designed | Load the page with `?mock=slow`, `?mock=error`, `?mock=empty` | A spinner alone, a blank page, an empty list with no action, or a failed save that clears the form |
| 9 | Fits a phone | Chrome device toolbar at 375 px | The page scrolls sideways or text overflows its cell |
| 10 | No console errors | Load every changed route in Chrome | Any error in the console, or a route that is not 200 |
