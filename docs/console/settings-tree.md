# Settings tree mock

Status: current (design mock for card c-178; nothing in it is stored, and no live page or route has moved).

The settings standard was adopted from the UX review of 2026-10-17
and asked for a mock before anything moves. `/preview/settings` draws the proposed tree on sample data. It runs on a
development server only (`src/proxy.ts` answers 404 elsewhere).

## Where things are

| Home | Opens from | Pages |
|---|---|---|
| My account | avatar menu | profile, password, two-step, sessions, my notifications (autosave) |
| Team | team switcher | General, Notifications, Webhooks, API keys |
| Workspace | team switcher | General, Storage |
| Govern | app sidebar | Access, Policies, Security, Models |
| Examples | settings sidebar | an agent's Settings tab, a tool page that opens dialogs, the field kit |

The S01 to S43 mapping is `S_MAP` in `src/lib/settings-preview.ts`, shown as a table on `/preview/settings` and checked
by `src/lib/settings-preview.test.ts` (43 entries, each pointing at a page of the tree or a live page).

## Patterns

| Pattern | Rule |
|---|---|
| Settings shell | Entering settings swaps the app sidebar for a settings sidebar: back arrow, Find box (F), a flat section list, personal items at the bottom (`components/settings/preview/settings-sidebar.tsx`) |
| One card, one Save | Every shared setting is a `SettingCard` with its own Save; the footer holds the constraint. Personal toggles save on change |
| Roles | A `locked` card or row shows the role's name; the mock's role switch in the sidebar footer shows both states |
| Page and dialog | A settings form is one component with two shells, `card` and `dialog` (`FormShell`) |
| Header | Page actions sit in the header's actions slot; History links to the one Audit log |
| Danger zone | Last, one `DangerCard` per action, each stating its precondition; type the name to confirm |

## Dialogs and their mother pages

| Dialog | Form | Same form on | Server call |
|---|---|---|---|
| Add allowed host | `EgressHostForm` | Govern › Security › Egress | `POST /v1/egress/hosts` |
| Add secret | `SecretForm` | Govern › Security › Secrets | `POST /v1/secrets` |
| Model alias | `ModelAliasForm` | Govern › Models › Aliases | `POST /v1/models/aliases` |

## Field kit

All in `src/components/shared/setting/`, shown on `/preview/settings/kit`: SettingCard, SettingRow and SwitchRow,
ChoiceCards, CopyField and CopyId, MiddleTruncate, SecretField, StatusDot, EntityRow, KeyValueEditor, UsageBar, Note,
DangerCard with DestructiveDialog, Combobox and MultiSelect, PrefixedInput, ScopeSelect, InheritSwitch with SourceBadge,
ImageSettingCard, GatedCard, SplitView (shadcn Resizable), ScrollTabsList, RecordTable. `ui/field`, `ui/item`, `ui/kbd`
and `ui/resizable` are from the shadcn registry unchanged apart from import paths.

## Known gaps

The mock stores nothing, so Save shows a message. Policies use the shape `GET` and `PUT /v1/policies` will serve (c-186):
key, value, default, role, effect. The sample data lives in `src/app/preview/settings/_sample/`, not in the mock API
layer, as `src/app/dev/knowledge-simple/sample.ts` does.

Proof: `make usecase-test UC=uc-126 LAYER=ui`.
