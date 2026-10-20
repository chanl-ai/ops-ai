# Table columns by kind

Status: proposed, approved in outline by the maintainers (via the orchestrator, 2026-10-18), waiting for the screens' sign-off.
Proof: `make usecase-test UC=uc-257 LAYER=ui`.

The shared data table sizes each column by what it holds (`apps/console/src/components/data-table-column-kinds.ts`):
ids, dates and statuses on one line at their own width; a name takes the free space and trims to one line with the
whole value on hover; a description wraps to two lines; numbers and money on one line, right-aligned; a cell that
draws nothing shows a dash. On a phone the select box and the name stay pinned while the other columns scroll.

| Table | Width at 1280 before | After |
|---|---|---|
| Workflows | 2745px | 1390px |
| Runs | 982px | 982px |
| Files | 1531px | 1499px |
| Members | 982px | 982px |

Each image is before beside after: `workflows-1280.png`, `workflows-400.png`, `runs-1280.png`, `runs-400.png`,
`files-1280.png`, `files-400.png`, `members-1280.png`, `members-400.png`.

Still wider than the page: Workflows and Files have more columns than fit at 1280, so they scroll inside the table with
the name pinned on a phone. Hiding columns by default would drop something from the screen, so it is left for the
owner to decide.
