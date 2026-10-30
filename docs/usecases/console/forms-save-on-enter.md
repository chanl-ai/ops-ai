# A builder saves settings pages and create dialogs with Enter

Status: current. Id: `uc-097`. Service: `console`. Layers: ui.

Card an earlier change: `DialogShell` and `SettingsSection` take `onSubmit` and render a `<form>`, so Enter in a field saves the
way the save button does, and every other button in them is `type="button"` so it never submits.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder of team_ops); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens New widget, types a name and a use-when line, and clicks Cancel | no widget is created |
| 2 | He opens it again, fills both, and presses Enter in the name field | the widget is created and its editor opens |
| 3 | He opens New guardrail, types a topic and presses Enter | the topic is added and nothing is saved |
| 4 | He fills the name and message and presses Enter in the name field | the guardrail is created |
| 5 | On Account, which is sample data (uc-125), he presses Enter in the name field | the field is off and nothing is saved or claimed saved |

Settings that save a new version on each save (Storage, Notifications) do not save on Enter; their Save button is the
only way to create a version, and [uc-106](lists-preview-and-versioned-saves.md) covers it.

## Acceptance layers

| Layer | Script |
|---|---|
| ui | `docs/usecases/console/scripts/test-uc-097-ui.mjs` |
