# A chat user never chooses between their own login and the team's

Status: current. Id: `uc-790`. Service: `tools-service` with agents-service and the console. Layers: api, ui.

A Human Task offered a chat user **Connect my account** beside **Run as the team account**, a choice they cannot judge.
Now a team admin answers one question per app, **Everyone uses the team's login** or **Each person signs in**. A
team-login action says which login acted and records who asked; an each-person app asks the person to sign in once, in
one card, and the chat carries on.

The api layer runs on `docs/usecases/lib/apps_walk.py` (the test plugins and the fake system). The ui layer runs the
console with the same plugins and a scripted model.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | On an app everyone uses with the team's login, an action runs with no sign-in and says it ran as the team login | api | 1 | 1 |
| S2 | The audit row of that action holds the team login and the person who asked | api | 2 | 2 |
| S3 | On an app each person signs in to, the person is asked once; after signing in the next actions ask nothing | api | 3 | 3 |
| S4 | Who signs in is changed only by an admin (`connections.manage`) | api | 4 | 4 |
| S5 | In chat, a team-login action says who acted under the reply, with no sign-in card | ui | 5 | 5 |
| S6 | In chat, an each-person app shows one sign-in card, the chat carries on after it, the next ask shows none, and nothing offers the team login | ui | 6 | 6 |
| S7 | The app page asks Who signs in with two answers, and the agent's tools row shows the app's answer | ui | 7 | 7 |
| S8 | A Human Task waiting for the person's sign-in offers them only Sign in | ui | 8 | 8 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA and Docker | `make db-up` |
| People | dev roles: admin Priya Shah and builder James Richardson (team_ops) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns the header key desk (`test.header-key`) on with the team's key; a call acting for James reads a record | 200, `ok`, `signedIn` `{whose: team, login: <the account's name>}` |
| 2 | Priya reads the call's row (`GET /v1/executions/{id}`) | `runAs` `{kind: team, login, askedBy: j.richardson@…}`, `actingFor` James |
| 3 | Priya turns the person key desk (`test.person-key`) on as Each person signs in; James's call; James gives his key; two more calls | The first is refused `CONNECTION_NOT_LINKED` (the sign-in card); the next two run as him (`signedIn.whose` person) |
| 4 | James (builder) changes the header key desk's sign-in; Priya reads it | 403; it still reads `team` |
| 5 | James asks the assistant for a record on the header key desk | The reply shows "Runs in Header key desk as … (team login). You are recorded as the person who asked." and no sign-in card |
| 6 | James asks for a record on the person key desk, gives his key in the card, then asks again | One card titled "Sign in to Person key desk to continue"; after his key the chat carries on with the record; the second ask shows no card; no text offers the team login |
| 7 | Priya opens the header key desk's Settings and an agent's tools | "Who signs in" reads Everyone uses the team's login and Each person signs in; the tools row names the app's answer |
| 8 | A run James started waits for his sign-in; he opens its Human Task | Only **Sign in to Person key desk**; no **Run with the team login** |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-790-api.py` | steps 1-4 |
| ui | `tools-service/scripts/test-uc-790-ui.mjs` | steps 5-7, at 1440 and 390 |

## Non-vacuous check

Step 2 reads `runAs.login` and `runAs.askedBy`: before this change a team call's row read `{kind: team}` alone and
fails it. Step 1 fails on a call answer with no `signedIn`.
