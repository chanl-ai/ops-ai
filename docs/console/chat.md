# Chat in the console

Status: current. How the chat thread is built, how tool results become widgets, and how a new use case adds
data rather than components.

## The thread is AI Elements, behind one wrapper

The chat page composes AI Elements blocks (`components/ai-elements/`, vendored from `registry.ai-sdk.dev`). Pages and
chat components never import them directly; `components/shared/chat-blocks.tsx` wraps the ones in use.

| Wrapper | Block | What it does |
|---|---|---|
| `ChatConversation` | Conversation | Scrolls the thread, sticks to the newest message while it streams, "Jump to the newest reply" |
| `ChatBubble`, `ChatAction` | Message, MessageActions | The person's bubble, the agent's open text, icon actions under each |
| `ChatResponse` | MessageResponse (Streamdown) | Markdown as it streams; `[n]` markers drawn as citation buttons |
| `ChatThinking` | Shimmer | What the agent is doing before text arrives |
| `ChatToolCall` | Tool | A tool call's name and state, open to show input and output |
| `ChatPrompt` | PromptInput | The message box; attachments go through the Files API, not the block |
| `ApprovalCard`, `StepList` | Confirmation, Task | The decision and steps widgets (`components/shared/approval-card.tsx`, `step-list.tsx`) |

The vendored blocks keep the console's own `components/ui` primitives; the upstream install would rewrite 13 of them.
Patches to the blocks are limited to type gaps and the standards gate (tokens instead of palette classes).

### Replies are not trusted markdown

A reply can carry text from documents and tool results, so `ChatResponse` never fetches an image (harden allows no
image prefix and shows "[Image blocked: alt]"; the `img` renderer draws no source) and links keep Streamdown's
link-safety confirmation. uc-074 checks that a reply with a remote image makes no request to its host.

## Widgets: a shape and data, never a component

agents-service shapes each successful tool result into a part and streams it as a `part` event after the tool call;
the message keeps it in `parts`, so a reload draws the same widget. No tool or server name is inside a part.

```
{ type: 'widget', id: 'wp_<toolCallId>', shape, data, hint?: { prefer?, title?, x?, y?, truncatedFrom? }, schema? }
```

| Shape | Data | Default renderer | Also |
|---|---|---|---|
| `rows` | flat objects | data table, 10 a page | line, bar, area when one text key and numeric keys exist |
| `series` | `{ x: [], series: [{ name, y: [] }] }` | line chart | bar, area, table |
| `record` | one flat object | field rows | table |
| `metric` | `{ value, label, unit?, delta? }` | stat card | |
| `form` | JSON schema and defaults | form | |
| `decision` | `{ summary, action, args, holdId }` | approval card | |
| `steps` | `[{ title, state }]` | step list | |

`lib/types/widgets.ts` is the contract; agents-service's `WidgetPart` (packages/contracts) matches it field for field.
`components/chat/widget-registry.ts` maps each shape to its renderers and picks one: the person's choice on this
widget, else a valid `hint.prefer`, else the default. `lib/widgets/convert.ts` holds the pure converters (rows to
series, series to rows, record to rows); both have `node --test` tests in `pnpm verify`. Rows cut at 200 by the
server carry `hint.truncatedFrom`, and the table says "Showing 200 of N rows".

Today the server emits `rows`, `series`, `record` and `metric`; `form`, `decision` and `steps` render on
`/dev/widgets` and wait for a server that sends them. Approvals in a thread still use the earlier approval widget.

## A tool declares its shape

An operation may declare its result shape with `x-ops-shape` on its success response (or the response's JSON media
type) in the OpenAPI document it is imported from; tools-service keeps it on import, and agents-service prefers it
when the data fits. Otherwise the shaper infers: rows from an array of flat objects, series when one key is a date
or a rising ordinal and the rest are numeric, metric from `{ value, label }`, record from any other flat object. An
answer that fits nothing stays a tool card.

```yaml
responses:
  "200":
    description: OK
    x-ops-shape: rows
```

## Adding a use case adds data

A new kind of result needs no new component: return data in one of the seven shapes, or declare `x-ops-shape` so a
series is shown as a table, and the registry draws it. Add a renderer only when a shape needs a way of drawing that
none of the existing renderers gives, and add it to the registry, not to a page.

## Where to see and check it

| What | Where |
|---|---|
| Every shape with sample data | `/dev/widgets` (dev server only), parts in `apps/console/src/lib/widgets/sample-parts.json`; uc-073 |
| Widgets through a real chat | uc-061 (fake bank's insights spec, scripted model) |
| The thread blocks, citations, remote images | uc-074 |
| Ask, cite, approve and reject in a thread | uc-072 (approval waits on platform step-up, an earlier change T022) |
