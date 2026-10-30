# A builder edits a widget with forms

Status: current. Id: `uc-103`. Service: `console`. Layers: ui. Card: an earlier change.

A widget's data fields, sample data and layout are edited with forms: a fields table, one input per field for the
sample, and the layout as nested blocks whose values are fixed or taken from a data field. JSON stays as the advanced
view. Limits written in JSON, such as a maximum length, survive a form edit. Design:
[chat widgets](../../console/chat.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |

The script creates its own draft widget through agents-service; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open the widget | Forms, no raw JSON box; the preview shows the sample title |
| 2 | Add a field `region`, sample `North` | A sample input appears for it |
| 3 | Add a Caption to the card, text from `region` | The preview shows "North" |
| 4 | Save draft | PATCH 200; the caption is `{ "$bind": "/region" }`, `region` is in the schema, `title` keeps `maxLength` 80 and `additionalProperties` stays false |
| 5 | Switch to JSON (advanced) | The layout JSON holds the binding |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-103-ui.mjs` | passing |

## Non-vacuous check

Step 4 reads the template back from agents-service. Dropping the kept keywords in `schemaOfRows`
(`apps/console/src/lib/widgets/schema-fields.ts`) loses `maxLength` and fails it, as `schema-fields.test.ts` also shows.
