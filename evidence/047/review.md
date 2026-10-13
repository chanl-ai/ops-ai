# c-047 independent review

One entry per commit, by a reviewer that did not build it. Checks ran on clean `git archive` exports of 1d8e51c, of
main at 291e765 and of bd91101, each with its own database; no working tree was edited. The walk ran on the builder's worktree stack
(console :5016). The card reached main ahead of review at the owner's request, so findings are fixed forward. Zero real
model calls.

## 1d8e51c: every sidebar parent lists its sub-pages as rows

- Check: `scripts/verify-head.sh` at 1d8e51c exits 0 (console, docs and every Python suite green). `make usecase-test
  UC=uc-047 LAYER=ui` on the export: 7 checks passed.
- Read: the parent row stays a link; a `SidebarMenuAction` chevron toggles a shadcn `Collapsible` around
  `SidebarMenuSub`, as `@shadcn/sidebar-08` builds it. `active = inSection && !hit.child` leaves the parent unlit on a
  child page, and the sub-row lights from `hit.child.url`. `open` is forced true for the current page's section, so a
  stored close can never hide the active row.
- Probes that held: `ops.sidebar.closed` set to `{"a":1}`, `not json`, `[1,null,"/knowledge"]` and `null` each left all
  sub-rows visible with no page error. In icon mode (Cmd+B) the sidebar collapses and no sub-row is visible.
- Note, not blocking: the stored state is read in an effect, so a parent the viewer closed renders open for the first
  frame and then collapses. Reading it in the state initialiser behind a mounted check, or accepting the flash, is the
  builder's call.
- Verdict: accept.

## 163a10d and 291e765: Files renamed and moved to its own Data Hub row

- Not on the card's branch and carry no `Feature:` trailer; both edit uc-047's expected children and were checked with
  tsc only. `make usecase-test UC=uc-047 LAYER=ui` on an export of 291e765: 7 checks passed.
- Defect, fixed forward in bd91101: `docs/usecases/console/sub-pages-in-the-sidebar.md` step 1 still listed Documents
  among the sidebar's sub-rows after Files became a top-level Data Hub row.
- Verdict: accept.

## bd91101: a one-child section lists its own page as a sub-row

- Check: `scripts/verify-head.sh` at bd91101 exits 0. `make usecase-test UC=uc-047 LAYER=ui` on its export: 7 checks
  passed. The use-case doc now lists the eight sub-rows and no Documents.
- Read: Workflows, Activity and Evals (one child each) gain a first sub-row for their own page, titled from `tabTitle`
  (All workflows, Tool calls, Suites); on that page the sub-row lights and the parent row does not. A closed one-child
  section reopens on its own page as well as on its child's.
- Probes that held: on :5016, Activity closed, then /logs/tool-calls reloaded: the section reopened with Tool calls the
  only active row; on /overview it stayed closed. /wiki (two children) lights the Wiki row itself.
- Gap, not blocking: uc-047 replaced its "a parent page lights the parent row" check with the one-child case, so the
  multi-child behaviour on /wiki is now covered only by this walk. A one-line check on /wiki would restore it.
- Verdict: accept.

walk repeated: on :5016 at bd91101, opened /logs/audit and chose Tool calls in the sidebar -> /logs/tool-calls opened with Tool calls the only active row and eight sub-rows listed; POST /v1/auth/sign-in 200, GET /v1/auth/session 200, no page errors. Earlier, at 1d8e51c, on :5016 signed in as the Lending Ops builder, opened /knowledge and chose Collections in the sidebar -> /wiki/collections opened with Collections the only active row, Wiki's Collections and Changes indented beneath it, Workflows, Activity and Evals open with their sub-rows; POST /v1/auth/sign-in 200, GET /v1/auth/session 200, GET /v1/workflows 200, no page errors

verdict: approve
