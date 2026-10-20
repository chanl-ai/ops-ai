# Human Task page (c-289)

Status: proposed, reworked after the owner's review, waiting for the design checker. Design: the
[Human Task page design](../../../design/human-tasks/task-page.md). Proof: `make usecase-test UC=uc-234 LAYER=ui` and
`make usecase-test UC=uc-224 LAYER=ui`.

A row in Human Tasks opens the task at `/reviews/<id>`, a record page on PageLayout: the question as the title, the
workflow, step and customer as the one-line description, the back icon to Human Tasks, status, risk and deadline as
badges, and the queue's position with Previous and Next as the actions. Below the header, the body is the only scroll
area and the decision is a footer row under it. With evidence (the document a read or a case is about, or the email
being answered) the body is two panes from 1024px, evidence first; below that an Evidence and Decide switch shows one.
Quick view on the row opens the queue's side view (896px, full content) without leaving the list.

The question and every value come from agents-service, worded from the tool's reviewer card when it has one and from
its input schema's titles otherwise (`services/agents-service/src/ops_agents/api/review_text.py`), so no tool name,
raw key or raw float reaches the page, and any workflow's step is worded the same way.

## Side by side

| Wireframe | 1280 | 400 |
|---|---|---|
| A, the page frame | `side-by-side-frame-1280.png` | `side-by-side-frame-400.png` |
| B, read check with key fields | `side-by-side-read-check-1280.png` | `side-by-side-read-check-400.png` |
| C, tool access request (generic held-action view until task types land) | `side-by-side-tool-access-1280.png` | `side-by-side-tool-access-400.png` |
| D, acknowledgement | `side-by-side-acknowledgement-1280.png` | `side-by-side-acknowledgement-400.png` |
| A held action with options (the levy case's hold or flag; no wireframe) | `task-held-action-1280.png` | `task-held-action-400.png` |

Other screens: `quick-view-1280.png`, `task-key-fields-confirmed-1280.png`, `task-read-check-1280-reason.png` (Reject
pressed without a reason: the footer gains the reason row and the body gets shorter).

## Where the build differs from the design

| Design | Built | Why |
|---|---|---|
| Wireframe C's specialised regions (the agent's reason first, tools with their effect, Grant and Refuse) | The generic held-action view: the question, each option with its consequence and values | Specialised types are task types (c-288); `components/tasks/task-regions.ts` is the one place that changes when they land |
| Kinds move to `components/kinds/` | `viewer` and `field_check` added in `components/chat/widgets/kind-view.tsx` | The move touches every chat import; a separate change |
| A held action's document shows boxes on the values in question | The document shows, without boxes | Boxes come from a read; a held action knows its file but not which read of it holds its values |
| D shows the received email above the reply, and each case with its amount | The reply, and each case by its subject | The reply step's summary carries the reply and the cases it started, not the received email; the case subject names the debtor |
| D and C show the decision buttons | Their screenshots are taken as people who may not decide, so the footer says who decides | The person who may decide is found per run; uc-234 step 8 checks C's buttons as that person |
