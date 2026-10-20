# An agent fills a pinned widget and lays out its own in chat

Status: current. Id: `uc-095`. Service: `console`. Layers: ui.

Card c-082: a builder pins published widget templates on an agent and lets it compose from the catalogue; in chat the
agent fills a widget with data checked against its schema, composes a layout, and a widget button sends its reply
back as the person's next message.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder); password `northfield-demo` |
| The scripted stack's widgets | `services/agents-service/tests/fixtures/seed/widgets.json`: hold-review (its button needs lookup_account), account-snapshot, case-summary |
| The scripted model | `call present <json>` calls the built-in present tool with those arguments |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens the agent page's Widgets section | Hold review cannot be chosen: it needs lookup_account, which the agent lacks |
| 1b | He grants lookup_account, chooses Hold review, switches on composing and saves | the version lists the widget; publishing makes it live |
| 2 | In chat he asks for the hold | a Hold review widget: payee as title, 12,500 USD held, a warning badge, Look up the account and Keep it held, footer "Hold review · v1" |
| 3 | He clicks Look up the account | his next message names the action and account, and the agent calls lookup_account once |
| 4 | He asks for a summary the agent lays out itself | a card marked "Composed by the agent" |
| 5 | He asks for a widget the agent was not given | no widget draws |
| 6 | Reload | both widgets draw again from the stored parts |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-095-ui.mjs` | passing |

## Non-vacuous check

Step 2 fails if agents-service drops the agent's widget pins at publish: present refuses the widget and nothing draws.
