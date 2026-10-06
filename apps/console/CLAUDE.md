# Ops AI console: working rules

Status: current.

Ops AI is the operations console for a bank's AI agents (demo tenant: Northfield Bank). These rules are
enforced by `pnpm verify` (type-check + `scripts/check-standards.mjs`), which the pre-commit hook runs.
A rule that is not checked by the script is still a rule; the script covers the ones a grep can prove.

## Layers (one direction only)

| Layer | Path | May import | Must not |
| --- | --- | --- | --- |
| Types | `src/lib/types/` | nothing app-level | contain data |
| API contract + clients | `src/lib/api/` | types | be imported by components |
| Mock (the only fixtures) | `src/lib/api/mock/` | types, contract | be imported outside `src/lib/api/` |
| Hooks | `src/hooks/` | api, types | render UI |
| Components | `src/components/` | types (type-only), other components, hooks for local UI state | fetch data or import `@/lib/api` values |
| Pages | `src/app/` | components, hooks, types | define fixtures or call `api` directly |

- Every value a screen shows comes from a hook backed by `OpsApi` (`src/lib/api/contract.ts`). Adding data means: type → contract → `http.ts` → mock → hook.
- Counts, totals and stats are computed by the API, never aggregated in a component.
- `NEXT_PUBLIC_OPS_API_URL` set → real HTTP client; unset → mock. Nothing else reads env.

## Components (reuse before writing)

| Need | Use | Never |
| --- | --- | --- |
| Page header | `PageLayout` (icon, title, one-line description, actions, `backHref` on record pages) | hand-built headers |
| List | `DataTableWithViews` + `DataTableColumnHeader` + faceted filters with counts + server pagination via `useListParams` + `selectColumn` + bulk actions | raw `<table>`, client-side paging of full lists |
| Create one thing (≤ 7 fields) | `DialogShell` size `md`, then navigate to its page to edit | a `/new` page |
| Create in steps | `DialogShell` + `Stepper` ("Step X of N", Back/Next, editable review step, fixed body height) | a wizard page |
| Revisitable settings | Form on the page (`SettingsSection`, sticky unsaved bar, versioned save) | a settings dialog |
| Inspect a row | `DetailSheet` with prev/next and `scrollKey` | navigating away for a peek |
| Delete | `DeleteDialog` with consequence text (`count` for bulk) | `confirm()` |
| Bulk change | `BulkConfirmDialog` / `BulkFieldDialog` + `toastBulk` (skipped items named by reason) + `useSticky` | silent partial success |
| Record page | `RecordLayout` / `AttributeCard` / `FieldRow`, or a settings form with a right rail | bespoke grids |
| Field | `FormField` (label, "(optional)", hint, inline error, `aria-invalid`) | placeholder-as-label |
| Upload a file | `FileUpload` (`components/shared/file-upload.tsx`): presigned upload through the Files API, progress, scan state, limits from Settings → Storage; pass the `fileId` on | `<input type="file">` with your own request, `FormData`, `fetch` PUT of a `File` (`check-standards` rule 13) |

`components/ui/*` are shadcn primitives adapted from the shared component library: do not edit them; wrap them in
`components/shared/`. Pages adapted from an earlier internal product keep their layout and copy but must be moved
onto the components above and the layer rules before they merge.

## States (every data surface)

- Loading: `PageSkeleton` / `RecordSkeleton` matching the real layout.
- Error: `QueryError` with Try again; record pages also offer a way back.
- Empty: `ListEmpty` / `EmptyState` with the create action; filtered-empty says so and offers Clear filters.
- Review them with `?mock=slow`, `?mock=error`, `?mock=empty` (`?mock=off` resets).

## Behaviour

- Production-affecting actions (publish, promote, move version, gate edits, deletes) confirm with the consequence stated.
- Workflows are the only deployable unit; agents are versioned settings pinned by a workflow at publish.
- Publishes are requested, validated (tests advisory, structural errors block) and approved by a different person in Reviews.
- Effects never return a value (`useEffect(() => { … })`): an expression body that returns a Promise or element crashes React.

## Copy

Product copy only: no developer explanations, no "(s)" plurals (use `plural()` from `src/lib/format.ts`), sentence case,
buttons say the action, placeholders start with "e.g." and never look like real records, numbers have units.

## Done means

1. `pnpm verify` passes.
2. Every changed route returns 200 and renders in Chrome without console errors.
3. An independent reviewer (a person or a fresh coding agent, in a browser, this file and `docs/ui/page-plan.md` as the standard) has exercised the change, and its blockers and majors are fixed.
