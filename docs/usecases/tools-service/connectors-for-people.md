# Connectors for people

Status: current. Id: `uc-671`. Service: `tools-service` with agents-service. Layers: api, ui.

Each person sees the apps that act as them as Connectors › Mine: one row per app, never one per account, with what
the app can do as them (built from the tools the team switched on, a write marked when it waits for approval), whom it
signs in as (named by the sign-in itself), its state, and where it is used. An app the team has off is listed so the
person can ask for it, and a call on it is refused as `APP_OFF_FOR_TEAM` naming the app and team, which chat draws as a
card. Every connected connector is on in a new chat; the composer's picker narrows one chat, stored as that thread's
`toolsOff`, and never adds a tool. Connectors › Team setup is the admin's view of the same apps (the Apps page,
unchanged in content), read only for a member.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S12 | A person's connectors are one row per app with its accounts as a count, what it can do, whom it signs in as and their own calls this week; an app off for the team is listed off | api | 1-4 | 4 |
| S13 | A call on an app the team has off is refused naming the app and team, and a chat's connector set narrows only that chat | api | 5 | 5 |
| S14 | The SDK and the CLI read the same rows and disconnect a connector's primary account | api | 6-7 | 7 |
| S15 | Connectors › Mine shows one row per app with one action by state, a details sheet, and fits a phone | ui | 8-10 | 10 |
| S16 | Chat's composer lists the chat's connectors with their actions, and an app off for the team is a card | ui | 11-12 | 12 |

## Preconditions

| Needs | How |
|---|---|
| The Apps stack | `docs/usecases/lib/apps_walk.py`: platform-service with the seed's roles, tools-service with the test plugins, the fake system |
| People | Priya (Operations admin), Sam (Security admin), Ravi (Operations viewer) |
| For the ui layer | The script builds its own stack (`withUiStack`) with the Salesforce plugin and Ops AI's own app for it, the fake Salesforce, Salesforce on for Operations and given to the team's assistant, and Priya signed in to it as herself. It never reads the local dev stack |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns Person desk on (each person signs in), adds a second account and signs in to both | `GET /v1/me/connections` has one Person desk row: `accountCount` 2, the team's default account primary, `account` the name the sign-in gave |
| 2 | She reads the row | `canDo` "Reads: Read a record", each tool with its access and `reviewed` |
| 3 | A call acts for her with both accounts connected and no default; she saves the second as her default; the call again, and a run acting for nobody | 403 `ACCOUNT_CHOICE_NEEDED` naming both accounts; then it runs as the second and `used.callsThisWeek` is 1 |
| 4 | Sam reads his connectors in Security, where Person desk is off | The row's `appState` is `needs_auth_config` (Security has no auth config for it), with no accounts and `mayManage` true |
| 5 | A call acting for Sam in Security on Person desk | 403 `APP_OFF_FOR_TEAM` with details `app`, `appId`, `teamId` |
| 6 | `ops.me.connectors.list()` as Priya | The same rows |
| 7 | `opsai connectors list`, then `opsai connectors disconnect "Person desk"` | The row is listed; after the disconnect of her default the other account is primary and the count is 1 |
| 8 | Priya opens Connectors in the sidebar at 1280 and searches | The title reads Connectors with Mine and Team setup; one GitHub row with "+1 account"; each row one action by state; "git" finds GitHub alone, "jira" none; an app the install lacks is not listed |
| 9 | She opens a row | The details sheet: what it can do with Read, Write and Reviewed; Used by as counts and links; the accounts; Test now and Disconnect |
| 10 | At 390, light and dark | The state and action sit inside the connector cell and inside the viewport; no screen says Apps or My accounts |
| 11 | Priya opens the composer's connector picker in a chat, and on Chat's home before a first message, and unchecks Salesforce | It was checked; apps needing a sign-in or off for the team are listed in their groups; Salesforce's tools leave that chat only, and a chat started from the home takes the choice before its first message |
| 12 | Ravi opens Connectors › Team setup and an app's page; Sam asks chat for his Salesforce cases | Ravi sees no Add custom app and no Connect; Sam's reply shows the off-for-team card |
| 13 | Priya, with two GitHub accounts and no default, asks chat for open issues, then opens GitHub on Mine | The chat asks which account with a card; Mine says chat asks which until she chooses, and Use in chats makes one her default |

Chat scripts: `make chat-script FILE=docs/usecases/chat/salesforce-off-for-team.yaml AS=sam`,
`make chat-script FILE=docs/usecases/chat/connectors-narrowed.yaml AS=priya` and
`make chat-script FILE=docs/usecases/chat/github-which-account.yaml AS=priya`.

## Scripts

| Layer | Script | Pass when |
|---|---|---|
| api | `tools-service/scripts/test-uc-671-api.py` | steps 1-7 pass |
| ui | `tools-service/scripts/test-uc-671-ui.mjs` | steps 8-13 |

## Not covered

Ask an admin's request and the admins' Human Task (POST /v1/requests, a separate story); until then Ask an admin
names the team's admins with mail links. A saved default is the person's default for every call that names no account,
not for chats alone.
