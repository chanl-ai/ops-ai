# Install and turn on a plugin

Status: current. The steps below are run by the plugin use cases listed in [Building a plugin](plugins.md#proof).

A plugin reaches a team in two steps. The person who runs Ops AI installs it once for the whole install, and from then
on every team is offered its App; each team then turns the App on and signs in. This page covers both, for a script
and for an image, and how an installed plugin is updated. Writing a plugin is in [Building a plugin](plugins.md).

## Install a plugin

| How | When |
|---|---|
| Put its folder in the install's plugins folder (`plugins/` in the repo, `OPS_PLUGINS_DIR` in Docker and Kubernetes) | Every plugin an install runs, built-in or brought by a customer |
| Add it to the environment tools-service runs in (`uv add`) | A packaged plugin on a developer's stack |
| List its folder in `OPS_PLUGIN_PATHS` (a JSON list) | A plugin under development, without copying it |

A plugin found in two places, such as a copy in the plugins folder and a checkout in `OPS_PLUGIN_PATHS`, loads from
neither: `GET /v1/plugins` reports each with both places, so a stale copy can never run in place of the checkout. The
local stack's plugins folder is the main checkout's `plugins/`, whichever worktree runs the stack;
`make demo-salesforce` installs the Salesforce plugin there from the plugins repository at its pinned ref.

`opsai plugin install <folder>` validates the plugin, then copies its package folder into the plugins folder (`--into`
names it when it is not `./plugins`), replacing an earlier copy whole; a plugin that fails validation is not copied.
`opsai plugin remove <id>` deletes it. Restart tools-service and kb-service after either.

```
uv run opsai plugin install ../ops-ai-plugins/plugins/salesforce
uv run opsai plugin remove opsai.salesforce
```

Compose mounts the checkout's `plugins/` read-only at `/plugins` in tools and kb (`OPS_PLUGINS_HOST_DIR` names another
host folder), so `opsai plugin install --into <that folder>` then a restart of both is the whole install.

### Plugins in a built image

The release image (`deploy/fly/Dockerfile`) ships the plugins `deploy/plugins.json` pins, in `/app/plugins`, which is
its `OPS_PLUGINS_DIR`. One build stage bakes them, and the service and runtime images copy that folder, so the two
cannot ship different plugins. Each pin names a GitHub repository, a full commit, the plugin's folder in it and the
sha256 digest of that folder:

```json
{"source": "https://github.com/chanl-ai/ops-ai-plugins", "ref": "<40-character commit>", "path": "plugins/salesforce",
 "sha256": "<64-character digest>"}
```

The build fetches each commit as a tarball, checks the plugin folder against its digest before installing anything,
validates the plugin as `opsai plugin install` does, and stops on any problem. A pin with no digest, or a download whose
folder differs from it, stops the build, so a swapped or altered archive never reaches an image. The digest covers each
file's path and bytes, not the archive, so it does not change when GitHub recompresses a tarball. A branch or tag is
refused, so an image built twice from the same commit holds the same plugins. To ship a newer plugin, run
`make plugins-bump` (it writes the commit and the digest together), review the plugin's change between the two commits,
and rebuild; mounting another folder at `OPS_PLUGINS_DIR` replaces the baked ones. To bake them into a folder
yourself: `uv run python deploy/images/bake_plugins.py --into ./plugins`.

### Pinned plugins on a laptop and a box

`deploy/plugins.json` is the one list of plugins for the image, a laptop and a cloud box. These commands keep the
plugins folder equal to that list:

| Command | What it does |
|---|---|
| `make plugins-sync` | Puts the pinned plugins into `OPS_PLUGINS_DIR` (default: the main checkout's `plugins/`). Plugins that are there and were not put there by this command move to `plugins.bak-<date>/` and are never deleted. `make box-up` runs it in a box |
| `make plugins-sync PLUGINS_DEV=../ops-ai-plugins` | Links the plugin folders of a working copy instead of the pinned commit, so an edit shows after the next restart. Run `make plugins-sync` without `PLUGINS_DEV` to go back to the pinned ones |
| `make plugins-bump` | Moves every pin to the current main of the plugins repository and prints the old and new commit per plugin. `REF=<branch\|tag\|sha>` moves to that instead; the file always records the full commit and the plugin folder's sha256 digest at it |

Restart tools-service and kb-service after a sync.

The staging deploy (`make stg-deploy`) checks the running app: the plugins in its `OPS_PLUGINS_DIR` must match
`deploy/plugins.json` by id and version, or the deploy fails (see [Fly staging](../deploy/fly-staging.md)).

tools-service and kb-service load every plugin when they start. A plugin that fails validation is left out and logged
at start as `plugin_failed` with its error, and every other plugin still loads.

## Turn a plugin on

An install with no plugin loads nothing: the plugin routes answer 404 and kb-service refuses a plugin source
(`tools_unavailable`). A plugin that loaded is offered to every team: installing it is the platform admin's decision,
and taking it out of the plugins folder is how it is withdrawn. The team's switch, its settings and its sign-in are the App's Connect window in the console ([Apps](apps.md#turn-an-app-on)); the calls below are the same steps for a script.

Ops AI's own OAuth app for a plugin, which every team uses unless it brings its own, comes only from the install
config. Register the app once with the vendor and set its client in the deploy's secret store:
`OPS_PLUGIN_CLIENTS='{"opsai.salesforce": {"id": "<client id>", "secret": "<client secret>"}}'`. tools-service reads
it at start and never writes the secret to the database; no route sets or shows it. A team's own client is kept once,
in `app_credentials`, and the accounts that sign in with it point at that row.

| Who | Call | What it does |
|---|---|---|
| Platform admin | install config `OPS_PLUGIN_LOCKED='{"opsai.salesforce": {"api_version": "61.0"}}'`, then restart tools-service | Fixes a lockable setting for every team; taking the plugin out of the plugins folder stops every team's calls, which then read "isn't installed on this system" |
| Team admin (`connections.manage`) | tools-service `PUT /v1/apps/plugin:opsai.salesforce/team` with `{enabled, settings, signIn, kind, credentials, clientId, clientSecret}` | Turns it on for the team and makes the team's default account, whole, for its sign-in kind (below); off again keeps the account and settings |
| Team admin | `POST /v1/apps/plugin:opsai.salesforce/accounts` with `{name, sandbox: true, ...}` and the same sign-in fields | Adds a sandbox account (a Salesforce sandbox org, for example). Test runs use it; live runs never do. Its sign-in address and the instance its sign-in names are its own |
| Security | nothing for the plugin's own hosts | The hosts in the manifest's `egress` (rendered with the team's settings) are reached by that plugin's sign-in, token, test and tool requests without listing; no other call reaches them unlisted. Private, loopback, link-local and metadata addresses stay refused |
| Team admin | `POST /v1/apps/plugin:opsai.salesforce/accounts/{id}/sign-in`, then `/sign-in/complete` | Signs the team in; `from_token` settings are read from the token answer here and kept on that account |

The first turn-on makes the account in one call, whatever the plugin's kind. `kind` picks one of the plugin's
`connection.kinds` (the first when left out) and cannot change once the account exists (`kind_fixed`).
`credentials` holds the kind's own fields: a key is sealed and never answered back, and a later turn-on that sends one
part replaces only that part. Test connection reads the manifest's `health_check` for every kind.

| Kind | `credentials` | What tools-service adds to each call |
|---|---|---|
| `none` | nothing | nothing |
| `api_key` | `key` | the key in the header or query parameter `connection.api_key` names |
| `basic` | `username`, `password` | `Authorization: Basic` |
| `bearer` | `token` | `Authorization: Bearer` |
| `oauth2_client_credentials` | none; `clientId` and `clientSecret` beside it, or the platform's app | a token from `token_url`, fetched and renewed by tools-service |
| `oauth2_auth_code` | none; the OAuth app as above | the team's or each person's token after they sign in |
| either OAuth kind, app proves itself with its certificate | `clientAuth: private_key_jwt`, `signingCertificate`, `signingKey`; `clientId` beside it, no client secret | a token asked for with a client assertion signed by the key (RFC 7523), on every token request, refresh, sign-in and disconnect; Microsoft Entra apps at banks |
| `oauth2_jwt_bearer` (signed service account) | `signingKey`, optionally `signingCertificate`, `subject`, `audience`, `scopeIn` (`form` or `claim`); `clientId` is the issuer | a token whose grant is a JWT signed by the key, signed again when it expires; DocuSign (client id = integration key, `subject` = user id, `audience` = `account-d.docusign.com`) and Google (client id = service account email, `scopeIn: claim`) |
| any kind | `clientCertificate`, `clientKey`, `trustedCa` | the client certificate on the TLS handshake; a refused handshake fails `TLS_FAILED` |

A wrong key, password or token fails Test connection naming the system's 401 and a call with `UPSTREAM_ERROR` 401; a
wrong client secret fails the token fetch with `AUTH_FAILED` and marks the connection `needs_reconnect`. A Python tool's
answer is scrubbed of the connection's credential, as a data tool's is.

The signing key and certificate are their own pair, apart from the mTLS `clientCertificate` and `clientKey`, so the
signing key is never offered on a TLS handshake. Saving a key that does not belong to its certificate is refused naming
both, also when only one half changes. Every read shows the certificate's SHA-256 thumbprint, subject, expiry and
whether it expires within 30 days, never the key. A certificate past its expiry is refused before any token request,
as `AUTH_FAILED` "the signing certificate expired on <date>", and marks a team connection `needs_reconnect`. The
system's own refusal of an assertion (another key, a replay) is `AUTH_FAILED` naming its host and error, and is never
retried with a secret. RS256 (RSA keys) and ES256 (P-256 keys) are the algorithms; any other key is refused.

A team that gives `clientId` and `clientSecret` signs in with its own OAuth app; one that gives neither uses the
platform's. `signIn` is `team` (one team login, shown as Everyone uses the team's login), `person` (each person signs in with their own login, from the chat card
or My apps, and calls act as them) or `person_or_team` (Each person signs in, with the team login for runs nobody started). A plugin
lists which of these it allows. One team's app, connection or token never serves another team, and one person's token
never serves anyone else.

On a connection each person signs in to, a key, password or token kind asks each person for their own: the
team gives the address and how the key is sent, and no key of its own. A person gives theirs with
`PUT /v1/me/accounts/{id}/credentials` and `{credentials: {key}}` (`{username, password}` for `basic`,
`{token}` for `bearer`), from the chat card that asks for it or from My accounts; it is sealed in their own row and
never answered back. `GET /v1/me/accounts?every=true` lists every account of the team a person can connect, with
`connected`, the method and the fields to give. A call acting for a person with no key is refused
`CONNECTION_NOT_LINKED` naming `authKind` and `personFields`, so the console asks for the key in place; a call with
nobody behind it is refused with reason `no_person`. A wrong key fails that person's call with the system's 401 and
leaves everyone else's working; Disconnect removes it.

### Several accounts of one app

A team keeps several named accounts of one app: two Salesforce orgs, two GitHub servers. Each account has a name that
no other account of the app in the team holds (case and spaces aside), held by a filtered unique index on
`connections.account_key` (`services/tools-service/migrations/versions/0071_account_key.py`), so two adds at the same
moment make one account and the other is refused 409 `account_name_taken`.

| Who | Call | What it does |
|---|---|---|
| Whoever holds `connections.manage` | `POST /v1/apps/{app}/accounts` with `{name, settings, makeDefault}` | Adds a live account signing in where its `settings` say (its own sign-in address); `makeDefault` makes it the team's default. A test account cannot be the default |
| Any member | `POST /v1/me/accounts/{id}/another` with `{name, settings}` | Adds a second account of their own, signing in where `settings` say. Only for apps that sign in with an account; with no body it is named "<person>'s other account" and signs in where `{id}` does |
| Any caller | `GET /v1/apps/{app}/accounts?usable=1&name=…&mine=1` | The accounts a call may name, each with `identity`: `usable` keeps the team's live accounts (what a workflow step or an agent names), `mine` adds the caller's own, `name` keeps the one so named |
| A run | `POST /v1/calls` with `runContext.accounts: {appId: name}` | Each app's call uses the account named for its app; `runContext.account` (one name) is still read |
| A builder | an `ops.action.tool` step's `accounts` parameter, or an agent's `accounts` (`PATCH /v1/agents/{id}`) | The step's or agent's choice per app. Publishing checks each against tools-service (`?usable=1&name=`) and refuses 422 `account_name_unknown`; a draft may name one not made yet |
| A person | `PUT /chat/threads/{id}/connectors` with `{off, accounts}` | The chat's choice per app, kept on the chat; `GET` lists each app's accounts when it has two or more, and `account` in use |
| A delete | `DELETE /v1/apps/{app}/accounts/{id}` | Refused 409 `account_in_use` while a workflow draft or published version, or an agent, names the account, with `published`, `drafts`, `workflows` and `agents` in the details; tools-service asks agents-service's `GET /v1/account-uses` (the same count as below), and refuses 503 when it cannot answer |
| Before a rename | `GET /v1/workflows/definitions/account-uses?app=…&name=…` | How many drafts and published versions name the account. A rename rewrites none of them: a published version is refused at its next call until its next publish names the new name |

Agents-service sends what was chosen and never picks or compares names itself: a step's choice over a chat's over
the agent's, decided in one place (`domain/accounts.py` chosen_accounts); a call run with the team login keeps only
the step's. The model is told the account in use and where it points on its apps line ("Salesforce: on · uses EU org
(kestrel-eu.my.salesforce.test)", `api/apps_line.py`), read from the row's `pointsAt` (the first identity entry that
is not who signed in), so a person's email never reaches the prompt; it has no tool input to change the account. How a call's
account is chosen, in tools-service only (`plugins/host.py` `PluginHost.for_call` and `_named`):

| Case | Account used |
|---|---|
| The call names an account for its app | That account of the call's team. An unknown name is refused 404 `ACCOUNT_NOT_FOUND`, never the default |
| It names one person's own account | Only when the call acts for that person; otherwise 403 `ACCOUNT_NOT_YOURS`, so a step or schedule never signs in as someone |
| A test run names a live account | The app's test account; with none, 409 `SANDBOX_REQUIRED` |
| It names none and acts for a person with their own sign-ins | Their default; with two or more and none chosen, `ACCOUNT_CHOICE_NEEDED` |
| Otherwise | The team's default |
| The named account's team sign-in ended (expired, refused or revoked) | None: 200 with `AUTH_FAILED` in the output, its details naming the account (`connection`) and `connectedEvent`. A run waits on that event ("Sign in to EU org again to continue"), a chat draws the sign-in card, and an admin's new sign-in reports the event so the run goes on. No other account is tried |

Changing an account's who signs in from `team` to `person_or_team` with `teamBackup` makes a call acting for a person
sign in as that person, and a call acting for nobody (a schedule) keep the team's login (uc-709).

Every account row (the app's Accounts list, Connectors › Mine, the account pickers) carries `identity`: what tells it
apart, built once in `plugins/host.py` `account_identity`. A plugin's `connection.identity` names the settings to show;
with none declared it shows what the sign-in filled, then the account's own sign-in address, and for a custom app its
address; who signed in comes last. A second account pointing at the same place carries `samePlaceAs` with the first's
name, a warning only. A member's Accounts tab lists the team's accounts and counts their own sign-ins (`me.signIns`);
their own accounts are on Connectors › Mine. Each team row also carries `signIn` (whose login its calls use: `team`,
`person` or `person_or_team`) and `peopleSignedIn` (how many people hold their own sign-in on that account). The row's
Settings dialog (`components/connections/account-settings-dialog.tsx`, apart from Connect, which signs in) changes the
name, who signs in and the auth config; the team default is the star on the row; "Each person signs in" shows the count against
the team's members, and a rename or a change of who signs in first shows how many drafts and published versions name
the account. A first turn-on through Ops AI's app keeps the sign-in address it asked as
a default on Ops AI's auth config, so a second account may type its own; a team whose first turn-on kept it fixed keeps
it fixed, and adds an auth config holding the address as a default for a second org.

### Package apps

A package app is a plugin whose tools run inside another app, such as a lending or life-sciences package installed in
a Salesforce org. It has no accounts of its own: each call signs in with the chosen account of the app it runs on and
reaches that account's address. The manifest says so in `connection`:

| Field | What it does |
|---|---|
| `kinds: [none]` | Required with `runs_on`: the package never signs in by itself |
| `runs_on` | The plugin id of the app it runs inside (`opsai.salesforce`). `endpoint`, `egress` and headers render with that app's settings for the chosen account, so `{instance_url}` is the org's |
| `requires` | The objects the package installs in the app. Optional |
| `requires_check` | A path from `/`, with `{name}` for each required object, that answers 404 or 400 where the object is missing (`/services/data/v{api_version}/sobjects/{name}/describe`). Required with `requires` |

`opsai plugin validate` refuses `runs_on` with another kind, `runs_on` naming the plugin itself, `requires` without
`runs_on`, and a check path that names no object. Turning a package on for a team makes no account, and is refused
409 `host_app_missing` when the install lacks the app it runs on.

| Case | What happens (`plugins/host.py` `PluginHost.for_call`) |
|---|---|
| A call names an account under the app it runs on (`runContext.accounts: {"plugin:opsai.salesforce": "EU org"}`) | The package's tool signs in with that account, chosen as that app's own calls choose one (`_choose`) |
| A call names an account under the package's own app id | 404 `ACCOUNT_NOT_FOUND`: the package has none |
| The app it runs on is off for the team, or not installed | 403 `APP_OFF_FOR_TEAM` naming that app, or `PLUGIN_DISABLED` |
| The chosen account's last Test found a required object missing | 409 `PACKAGE_MISSING` naming the account, before any request leaves tools-service |
| The account was never checked (signed in before the package was installed) | The call runs; its next Test records the check |

The check runs with every passing Test, which also runs after each sign-in (`connections/service.py` `_packages`): it
reads each object's path through the account's sign-in and saves `health.packages` on the account, by package id, with
the objects missing. `GET /v1/apps/plugin:{package}/accounts` lists the accounts of the app it runs on, each with
`appId` (the key a step or agent names it under) and `missingObjects`, so a picker shows an account unavailable.
`docs/usecases/lib/plugins/loan_desk` is a fictional package for the use cases (uc-706).

After that, builders grant the plugin's tools to agents as any other tool, and a knowledge base adds a source with
`POST /v1/sources` and `{type: "tool", config: {plugin: "opsai.salesforce", source: "articles"}}`. Nobody can edit,
publish or delete the plugin's tool module; a new plugin version replaces it.

## Plugin updates

Behind the `plugin_updates` install flag (`OPS_FLAGS`), off by default; off, a plugin's tools are written once and
every team calls the installed manifest. On, each team runs the plugin version it took:

| What | How |
|---|---|
| The team's version | Its binding records the version, a digest of the tool declarations (the plugin-wide headers and each tool's manifest entry) and the declarations. A team takes the installed version when it turns the plugin on |
| An upgrade | The operator installs the new package and restarts tools-service. The account's tool row follows it, keeping each tool's id and a dropped tool as a switched-off row. Nothing changes for a team until it takes the update |
| Calls and lists | Built from the team's version: a changed tool keeps its request and inputs, a dropped one still answers and stays listed, a new one is neither listed nor callable. A Python tool always runs the installed package's function |
| The review | `GET /v1/apps/plugin:{id}/update`: both versions, and each new, changed and removed tool with its inputs added, removed and changed. agents-service's `GET /v1/tool-uses?tools=` names the team's agents and workflows that use each one |
| Taking it | `POST /v1/apps/plugin:{id}/update` with the installed digest the review was read at; another upgrade since then answers 409 `update_changed`. Keeping the current version is not taking it |

Not versioned per team: the sign-in (addresses, scopes, the lookup after sign-in), the endpoint and the egress hosts,
which are the installed version's. uc-609 (`make usecase-test UC=uc-609`) runs an upgrade from 0.1.0 to 0.2.0 across a
restart.

