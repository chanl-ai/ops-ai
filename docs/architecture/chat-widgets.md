# Chat widgets

Status: current, 2026-10-17. This is the design for card c-082, "A builder gives an agent widgets it can show in chat". The maintainers answered the card's five interview questions on 2026-10-17 (listed under Open questions). Phases P1 to P4 are built, and code is cited at commit `cd14ec5`. Use cases uc-089 and uc-095 prove the path. Planned items are marked. Sources: [chat](../console/chat.md) and the override model decision.

A chat widget is a shaped answer drawn in the thread. A builder lays out a named widget from a fixed catalogue of primitives, binds it to JSON Pointer paths in a JSON Schema for its data, and publishes it after a second person approves it. An agent pins the widgets it may show and may be allowed to compose its own layouts from the same catalogue.

The kernel's `present` tool has three forms:

| Form | What the model gives |
|---|---|
| `shape` | One of the four built-in shapes |
| `widget` | A pinned widget and its data |
| `layout` | A tree it composes |

The kernel checks every tree against the catalogue before any part leaves it. A button's click sends a message back to the agent in the thread. A button that requires a tool names that tool in its reply, and the agent calls the tool through its normal path, the data gateway and approvals.

Why: a bank wants an answer about a held payment to look like its own hold review every time, and wants to know that nothing on screen can act by itself. Reviewed templates and a catalogue-only check mean the console draws only primitives it knows. Buttons that only send messages leave every action on the agent's audited path.

### Where today's widgets stand against other platforms

| Platform | What it does | Ours is behind | Ours is ahead |
|---|---|---|---|
| OpenAI ChatKit widgets | JSON trees of about 24 components that the model fills. Actions go to the server, form fields bind by dot name, and payloads are untrusted | We have fewer primitives (14), and a button sends only a message | Results are shaped from tool output with no model involved (`services/agents-service/src/ops_agents/activities/shaper.py:1-26`). Templates are reviewed by a second person |
| MCP Apps (SEP-1865) | A `ui://` resource renders in a sandboxed iframe with a deny-by-default CSP and JSON-RPC over postMessage | We cannot show an MCP server's own UI | No third-party code runs in the console |
| OpenAI Apps SDK | `outputTemplate` links the UI. `structuredContent` is what the model sees; display data is kept apart | We have no split between data the model sees and data that is only shown | The same no-third-party-code point |
| AI SDK generative UI | Each tool maps to a developer-owned React component | | A builder adds a widget without a console release |
| A2UI | The model composes a flat tree from a pre-approved catalogue | A2UI streams the tree as it is built; we check the whole tree before drawing it | Composition is per agent, can be switched off per run, and each tree passes closed-field and size checks (`packages/ops_agent_kernel/src/ops_agent_kernel/layout.py:20-27`) |

Why this comparison: ChatKit's model (templates the model fills) and A2UI's model (composition from a catalogue) are both built, as the maintainers chose (Q2). MCP Apps iframes need governance of their own and stay last.

## Generic kinds (c-176)

Status: current. `present` has a fourth form, `kind`, for generic widgets that look the same in any industry; the
industry is in the data and its labels, never in the kind. Each kind is one JSON Schema in
`packages/ops_agent_kernel/src/ops_agent_kernel/kinds.py` (copied to `apps/console/src/lib/widgets/kinds.schema.json`
and compared in `services/agents-service/tests/unit/test_widget_kinds.py`). A `present {kind, data}` call fills the
kind through `layout.fill` with a binding generated from the schema, so it passes the same catalogue, closed-field and
size checks as any layout, and a builder's template can place a kind as a node and `$bind` its fields. No schema has a
field for a link, script, HTML or image source; a button, slot or form only sends a message back to the agent.

| Kind | Shows | Example in the gallery |
|---|---|---|
| `metric` | A figure with its change and trend; `goodWhen` colours the change | Open disputes (banking), online orders (retail) |
| `table` | Rows with named, formatted columns, sortable and paged | Card transactions, shipments |
| `chart` | Line, bar or area over one x key | Appointments by week, claims by line |
| `timeline` | Dated events with a tone | Claim history, customer activity |
| `tracker` | The steps of one process and where it is | A shipment, a mortgage application |
| `entity` | One thing with fields, a status and actions | A patient, a product |
| `comparison` | Options side by side, one recommended | Home insurance plans, savings accounts |
| `checklist` | Items done and not done | Account opening, before a procedure |
| `form` | Fields the person fills; Submit sends the answers as a message | Report a claim, request a callback |
| `confirm` | A yes or no before the agent acts | Place a hold, reroute a shipment |
| `document` | A cited file page with the passage marked; Open uses the file id | Cardholder agreement, discharge instructions |
| `quote` | A passage with its source, page and match confidence | Policy wording, returns policy |
| `plan` | What the agent will do, step by step | Settle a claim, recover a shipment |
| `reasoning` | How the agent got there, with what it searched | Dispute triage, referral booking |
| `slots` | Times to pick; picking sends a booking message | Clinic follow-up, branch meeting |
| `receipt` | Line items, tax and total in a currency | Retail order, freight invoice |
| `contact` | A person or place to reach, as text to copy | Claims adjuster, depot |

The console draws every kind, every shaped tool result (rows, series, record, metric, form, decision and steps,
converted in `apps/console/src/lib/widgets/kinds.ts`) and every kind inside a template through one renderer set,
`apps/console/src/components/chat/widgets/kind-view.tsx`, built from AI Elements, shadcn chart and shadcn components.
`/dev/widgets-polish` shows each kind in two industries with its loading, empty and error states; uc-132 has the
agent show all 17 in one chat.

## Record cards (c-469)

The team's default agent finds a person's work with the Ops tools and answers with record cards: one card shape for a
case, a Human Task, a workflow run and a workflow's start form. The widget kinds above stay for what an agent composes
itself; a record card is always drawn from the record.

| Part | Where | Rule |
|---|---|---|
| Ops tools | `services/agents-service/src/ops_agents/api/ops_tools.py` | Read only, offered to the team's default agent on a turn with a person, run as that person (`TURN_PERSON`) through the facade each route uses; they take no person or team argument |
| Card references | the tool's answer, stored on the thread | `{"cards": [{type, id}], "summary"}`: references, never field values |
| Filling | `fill_cards`, on every thread read (the console's and the embedded chat's) | Each reference is filled from the record's own route as the reader; a record gone or out of reach is `missing` |
| The card | `apps/console/src/components/chat/ops-card.tsx`, `lib/ops-card-mappers.ts` | Type and title, one status, facts or steps formatted by type, at most two buttons plus More, Open to the record's page |
| Buttons | `components/chat/record-cards.tsx` | The record's route as the signed-in person: a task is decided with `useDecideReview` and the `/reviews` step-up, shown only when the record's `canDecide` holds; a start uses the trigger's start form |
| Embedded chat | `apps/embed` | The same card with Open and no buttons, since the widget API serves no record routes |
| Ops Assistant | `ensure_ops_assistant` | A team with no default agent gets one on its first chat, set as default; its id comes from the team, so two first chats make one |

## Scope

| Phase | What | Status |
|---|---|---|
| P0 demo | uc-089 (`docs/usecases/console/agent-presents-widgets.md`): `present` draws a table and a stat in chat, refuses a shape it does not allow, and redraws both after a reload | built |
| P1 named widgets | `present` gains `widget`; agent versions pin widgets; the console draws filled layouts. The library is seeded from `services/agents-service/seed/widgets.json` | built |
| P2 composition | `present` gains `layout`, checked by `layout.check` | built |
| P3 authoring | Registry tables, `/v1/widgets` routes, publish through Reviews, the console `/widgets` list and editor with live preview, and the agent page's Widgets picker | built |
| P4 replies | A button sends its reply as the person's next message, naming the action when it requires a tool; uc-095 | built |
| Later | Display-only data the model never sees; MCP Apps iframes under their own install review | planned |

| Out | Where it is covered |
|---|---|
| The embedded chat widget on an intranet page | Chat (M7). It is a different thing that shares the word "widget" |
| Direct tool calls from a widget | Not built, by owner decision (Q3) |

Why: each phase was usable alone. The one later item, display-only data, changes what the model sees and needs its own review.

## Traceability

| Item | Source | Status |
|---|---|---|
| Owner request for richer widgets, authoring, a per-agent list and proof that chat generates them | `research.md` (2026-10-17) | built |
| c-055 widget architecture: shape parts | `docs/console/chat.md` | built |
| Caller overrides narrow widgets (c-071) | Commit f92a54a; override model | built |
| Buttons that require a tool | Agreed by the maintainers on 2026-10-17, after the live demo looped on a "Release hold" button that had no tool behind it | built |
| Interview Q1 to Q5 | `interview.md` | answered; see Open questions |

Why: each rule below traces to an owner answer or a decision, so a change to it is a change to a decision.

## Domain model

### Primitives and limits

| Primitive | Fields (closed) | Required |
|---|---|---|
| `card` | title; children | none |
| `row`, `column` | gap, align; children | none |
| `title`, `text`, `caption` | text | text |
| `badge` | text, tone, tones (a fixed value-to-tone table) | text |
| `metric` | label, value, unit, delta | label, value |
| `table` | rows, columns | rows |
| `chart` | rows, x, y, kind | rows, x, y |
| `keyValue` | items (label and value pairs) | items |
| `list` | items | items |
| `button` | label, reply, requires (a tool name) | label, reply |
| `divider` | none | none |
| `image` | alt, src | alt. It renders blocked, and its src is dropped |

The catalogue is defined at `layout.py:35-53`.

| Limit | Value | Defined at |
|---|---|---|
| Nodes in a tree | 200 | `layout.py:20` |
| Depth | 6 | `layout.py:21` |
| Children of one node | 50 | `layout.py:22` |
| Characters in one text field | 2,000 | `layout.py:23` |
| Text in a whole tree | 16,000 characters | `layout.py:24` |
| Rows in a table or list | 50 | `layout.py:25` |
| Columns | 20 | `layout.py:26` |
| Buttons | 10 | `layout.py:27` |

### Bindings and filling

A template binds data with `{"$bind": "<JSON Pointer>"}`. There is no expression language (`layout.py:1-8`, `bind` at `layout.py:252`). `fill` works in three steps (`layout.py:277-290`):

1. It validates the data against the template's JSON Schema (Draft 2020-12) and refuses with the first error.
2. It binds the data into the tree.
3. It checks the result as a composed layout is checked.

A node whose required field the data leaves out is dropped (`layout.py:197-199`). When nothing is left to show, the call is refused. The console's live preview uses the same binding rules (`apps/console/src/lib/widgets/bind.ts:21,47`).

### Tables

| Table | Columns | Defined at | Status |
|---|---|---|---|
| `registry_widgets` | id (a slug the agents pin), team_id, version, published_version, retired_reason, created_at, updated_at, updated_by | `services/agents-service/src/ops_agents/store/widgets.py:24-38`; migration `services/agents-service/migrations/versions/0032_registry_widgets.py` | built |
| `registry_widget_versions` | widget_id, version, content (name, useWhen, tree, dataSchema, sample), digest, changes, saved_at, saved_by, published_at, published_by, review_id | `store/widgets.py:40-52` | built |
| `registry_publish_requests` | kind `widget`, ids `WDP-` | `services/agents-service/src/ops_agents/store/agent_registry.py:298` | built |
| Seeded library | Platform-wide published templates served beside the registry | `services/agents-service/seed/widgets.json`; `services/agents-service/src/ops_agents/api/widgets.py:1-5,108-120` | built |

A published version is immutable, and retiring a widget refuses new pins while existing pins keep working. An agent version pins a widget by `{widgetId, version}`, and the pin is a snapshot of the reviewed tree (`services/agents-service/src/ops_agents/api/routers/agents.py:357`). The agent's widget settings are its pins, whether it may compose, and a maximum per answer (`services/agents-service/src/ops_agents/activities/catalog.py:99-102`).

Why: widgets mirror skills, versioned content published through review and pinned by version, so they reuse the same review and retirement rules.

## Behaviour

| # | Rule | Status |
|---|---|---|
| CW1 | `present` takes exactly one of `shape`, `widget` or `layout`; otherwise it returns a tool error (`present.py:159-162`) | built |
| CW2 | `widget` must be one of the run's effective widgets. Otherwise the error lists the agent's widgets (`present.py:169-173`) | built |
| CW3 | Widget data that fails its schema returns the error plus the widget's field list to the model (`present.py:174-177`) | built |
| CW4 | `layout` is refused unless the agent may compose. A composed tree passes `layout.check`, or the check's error goes back to the model (`present.py:183-188`) | built |
| CW5 | A part is refused when one of its buttons requires a tool that this turn was not granted (`present.py:148-149,180-181,190-191`) | built |
| CW6 | Pinning a widget whose button requires a tool the agent lacks is refused with 422 `widget_needs_tool`, and so is removing such a tool from an agent that pins the widget (`routers/agents.py:330-354`) | built |
| CW7 | A widget part carries the template ref (id, version, name) and the filled layout, so the console needs no template lookup (`present.py:178-179`) | built |
| CW8 | A click sends the button's reply as the person's next message. A button that requires a tool appends "(action: tool, key: value, ...)" (`apps/console/src/components/chat/widget-layout.tsx:43-50`). The agent calls that tool through its normal path and approvals | built |
| CW9 | Over the agent's per-answer cap, `present` returns "answer in text". The next `present` call ends the turn with `WidgetLimitReached`, keeping what was shown (`packages/ops_agent_kernel/src/ops_agent_kernel/kernel.py:142-185`) | built |
| CW10 | Each pinned widget adds one line to the `present` description, its id and its use-when line, as an implicit skill (`present.py:121-145`) | built |
| CW11 | A filled part shows the widget's name and version. A composed part is labelled "Composed by the agent" (`widget-layout.tsx:141-152`) | built |
| CW12 | Fields marked display-only are filled on the server from a tool result and never sent to the model | planned |

Decision on CW7: the part carries the filled layout instead of `{template, data}`. The thread then draws exactly what the kernel checked, a reload needs no registry read, and a later template version or a retirement cannot change a message already shown. The cost is a larger stored part, bounded by the tree limits.

Why: CW4 to CW9 enforce the safety model, and a test can break each one.

## API

### The `present` tool

The tool is built per turn (`present.py:121-145`). `widget` appears when the agent has widgets, with an enum of the agent's list. `layout` appears when the agent may compose. The node schema lists the primitives without `image` (`present.py:94-118`). The description adds the button rule: a reply is sent back as the person's next message and does nothing else (`present.py:90-92`).

```json
{
  "type": "object",
  "properties": {
    "shape": {"type": "string", "enum": ["rows", "series", "record", "metric"]},
    "widget": {"type": "string", "enum": ["hold-review", "case-summary"]},
    "data": {"description": "For shape, the rows, record or metric. For widget, an object with that widget's fields."},
    "layout": {"$ref": "#/$defs/node"},
    "hint": {"type": "object"}
  },
  "$defs": {"node": {"type": "object", "required": ["type"], "properties": {
    "type": {"enum": ["card", "row", "column", "title", "text", "caption", "badge", "metric", "table", "chart",
                      "keyValue", "list", "button", "divider"]},
    "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
    "requires": {"type": "string", "description": "A button's tool: one this agent holds."}}}}
}
```

The two widget forms are `{"widget": "hold-review", "data": {...}}` and `{"layout": {"type": "card", "children": [...]}}`.

### Part event

The existing `part` event carries a layout part, `{type: "widget", id, layout, template?: {id, version, name}}`. A part holds exactly one of `shape` and `layout` (`packages/contracts/src/ops_contracts/chat.py:198-226`; `apps/console/src/lib/types/widgets.ts:75-109`).

### Widget registry

| Operation | Notes | Defined at |
|---|---|---|
| `GET /v1/widgets` | The seeded library, then the caller's teams' widgets | `services/agents-service/src/ops_agents/api/routers/widgets.py:63` |
| `GET /v1/widgets/{id}` | Another team's widget is 404 | `routers/widgets.py:49-59,69` |
| `POST /v1/widgets` | Created in the caller's team | `routers/widgets.py:77` |
| `PATCH /v1/widgets/{id}` | Saves the draft | `routers/widgets.py:87` |
| `POST /v1/widgets/{id}/publish-requests` | Kind `widget`, id `WDP-`, decided in Reviews | `routers/widgets.py:100` |
| `POST /v1/widgets/{id}/retire` | Refuses new pins | `routers/widgets.py:132` |
| `PATCH /v1/agents/{id}` with `widgetPins` and `widgets` | Pins are snapshotted; 422 `widget_needs_tool` | `routers/agents.py:328-354` |
| Overrides `switchableWidgetIds`, `widgetsOff`, `composeOff`, `widgetsPerTurn` | Narrow only (c-071) | `services/agents-service/src/ops_agents/activities/agent_limits.py:51,114-115`; `activities/overrides.py:49-51`; `activities/catalog.py:236-238` |

Why: one tool with three forms keeps the model's tool list short, and the registry routes follow the skills routes, so the console and Reviews reuse their patterns.

## UI mapping

| Console route | What it does | Status |
|---|---|---|
| `/widgets` | Lists the library and the team's widgets with publish state | built (`apps/console/src/app/widgets/page.tsx`) |
| `/widgets/[id]` | Editor with the tree, data schema, sample data and a live preview through `lib/widgets/bind.ts` | built (`apps/console/src/app/widgets/[id]/page.tsx`) |
| Agent page, Widgets section | Pinned widgets, a composition switch and the per-answer cap (`apps/console/src/components/agents/agent-settings.tsx:224`). The picker shows the tools each widget needs and disables a widget whose tool the agent lacks (`apps/console/src/components/agents/widgets-dialog.tsx:39,75,94-96`) | built |
| Chat thread | Draws layout parts with a label (CW11); buttons send replies | built (`apps/console/src/components/chat/widget-layout.tsx`) |
| Reviews | Widget publish requests | built (`services/agents-service/src/ops_agents/api/publish_reviews.py:32-39`) |
| `/dev/widgets` | A gallery of shapes and sample layouts | built, dev only |

Authoring options weighed: a tree editor with live preview (built), a form editor for each primitive, JSON with live preview, and a visual drag-and-drop builder (later). The live preview fills the template with the same binding rules as the kernel, so a reviewer sees what a banker will see.

Why: the editor, the preview and the thread share one set of primitives, so what is approved is what is drawn.

## Security, audit and evidence

### How a layout is checked

Every tree, composed or filled, is rebuilt from the closed field lists before a part leaves the kernel (`layout.py:1-8`). The first failure goes back to the model as a tool error naming the JSON Pointer and the rule, and no part is emitted (`present.py:183-188`).

| # | Check | Rule | Defined at |
|---|---|---|---|
| L1 | Catalogue only | A `type` outside the catalogue is refused | `layout.py:190-191` |
| L2 | Closed fields | A field the primitive does not take is refused, each field is typed, and required fields must be present (a filled template drops the node instead) | `layout.py:192-201` |
| L3 | Size | The limits table above | `layout.py:20-27` |
| L4 | No code | No primitive takes HTML, script, style or event handlers. Text renders as text, and no link primitive exists | `layout.py:1-8` |
| L5 | Images | A composed layout with an image is refused. A filled template's image renders blocked, and its src is dropped | `layout.py:206-210` |
| L6 | Buttons | At most 10. A button's `requires` must be a tool this turn holds | `layout.py:211-214`; `present.py:148-149` |
| L7 | Per-answer cap | The cap from the agent or a narrowing caller | `kernel.py:142-160` |

| Control | Rule | Status |
|---|---|---|
| Who defines named widgets | Builders, in their team. Publishing needs someone who neither requested nor saved the version (`publish_reviews.py:95-98`) | built |
| Who may compose | The model, only for agents that allow it; a caller can switch composition off | built |
| Clicks | A click only sends a message. The named action is a request the agent weighs against its grants and the operation's approval policy. Reply text is untrusted input to the agent | built |
| Prompt injection | A tool result cannot draw a fake approval: the approval card is not a primitive, composed parts are labelled, images are blocked, and no links exist | built |
| Team scope | Another team's widget is 404; the seeded library is platform-wide | built |
| Audit | Widget publishes and decisions are review records, each part records its template version or composed tree, and a click is a message by the person who clicked | built |

Why: a widget is something a person trusts enough to click. Checking every tree on the server and turning every click into a visible message keeps each effect on the agent's audited path.

## Non-functional

| Concern | Target | Status |
|---|---|---|
| Tokens | Each pinned widget adds one use-when line to every turn. With no fixed cap, the builder sees the list on the agent page | built; a per-widget token figure is planned |
| Size | Bounded by the tree limits | built |
| Turn safety | A model that ignores the cap ends its turn at the next `present` call instead of using up the step limit (CW9) | built |
| Compatibility | Shape parts are unchanged, and a part drawn from a retired widget still draws, because it stores its layout | built |

Why: the cap and the turn ending are what stop a looping model from spending the turn's budget on widgets.

## Acceptance tests

| Test | What it checks | Status |
|---|---|---|
| uc-089 (`docs/usecases/console/agent-presents-widgets.md`) | A table and a stat in chat, a refused shape, and a redraw after reload | passing |
| uc-095 (`docs/usecases/console/agent-fills-widgets.md`) | 11 checks: a widget that needs a tool cannot be picked until the tool is granted; pin and publish; fill; a click names the action and the agent calls `lookup_account` once; a composed card; a widget the agent lacks draws nothing; reload. It fails if the pins are dropped at publish | passing |
| `services/agents-service/tests/unit/test_present_widgets.py`, `tests/api/test_agent_widgets.py`, `tests/api/test_widget_registry.py` | Kernel checks, pin rules and the registry | in `make verify` |

Why: uc-095 drives the real seam from the agent page through chat to the tool call, and its non-vacuous check is stated in the use case.

## Open questions

The interview questions, all answered by the maintainers on 2026-10-17:

| # | Question | Owner answer |
|---|---|---|
| Q1 | Who may define a widget? | Builders author named widgets from the catalogue; a widget goes live after a second person approves it |
| Q2 | May the model invent UI? | It may compose from the catalogue now, as well as fill named widgets. MCP-app HTML stays last |
| Q3 | What does a click do? | It sends a message back to the agent. Widgets take no direct actions |
| Q4 | What limits apply? | No fixed caps; the agent's own settings set them, and callers only narrow |
| Q5 | Is `present` the base? | Yes, with one implicit skill line per widget |

Answered since the first version of this page: templates belong to a team, and the seeded library is platform-wide. Composed layouts may hold buttons, under the same `requires` rule.

Still open:

1. Should "widget" in the UI be renamed to keep it apart from the embedded chat widget?
2. When does display-only data (CW12) ship?
3. Should composition be on by default for a new agent? Today it is off (`catalog.py:101`).

### Other possibilities

| Option | Verdict |
|---|---|
| A tool declares its widget, as `x-ops-shape` declares a shape, so the server draws it with no model step | Recommended next: deterministic and cheap |
| One tool per widget | Not needed: the three-form `present` validates well, and the tool list stays short |
| MCP Apps iframes | Last tier, with its own install governance |

Why: the remaining questions change a default or a UI word, so they do not block the built path.
