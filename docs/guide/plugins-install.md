# Install a plugin and turn it on for a team

Status: current.

Your teams want an app that Ops AI does not ship with, such as a CRM or a document service, and someone has written a
plugin for it. A plugin reaches a team in two steps, shown below. This page covers both
steps, for the console and for a script, and how an installed plugin is updated. Writing a plugin is covered in
[Building a plugin](plugins.md).

## Install a plugin

<!-- site: sequence caption="From a plugin folder to a team signed in: the person who runs Ops AI installs once, and each team turns it on" -->
1. **Platform admin → Plugins folder**: Installs the plugin once for the whole install
2. **Platform admin → Tools service**: Restarts the tools and kb services, which load every plugin that passes validation
3. **Tools service → Team admin**: Offers the app to every team
4. **Team admin → Tools service**: Turns the app on and sets its settings
5. **Team admin → Tools service**: Signs in, and the account is kept for the team

There are three ways to put a plugin in front of an install:

| How | When to use it |
|---|---|
| Put its folder in the install's plugins folder (`plugins/` in the repository, `OPS_PLUGINS_DIR` in Docker and Kubernetes) | Every plugin that an install runs, whether it is built in or brought by a customer |
| Add it to the environment the tools service runs in (`uv add`) | A packaged plugin on a developer's stack |
| List its folder in `OPS_PLUGIN_PATHS` (a JSON list) | A plugin under development, without copying it |

If the same plugin turns up in two places, such as a copy in the plugins folder and a checkout in `OPS_PLUGIN_PATHS`,
Ops AI loads neither of them. the `plugin_failed` entry in the start-up log names both places, so you can see which copy to remove, and a stale
copy can never run in place of your checkout.

The command line does the copying for you:

```
uv run opsai plugin install ../ops-ai-plugins/plugins/salesforce
uv run opsai plugin remove opsai.salesforce
```

`opsai plugin install <folder>` validates the plugin first, and copies its package folder into the plugins folder only if
it passes, replacing any earlier copy whole. Add `--into` to copy into a folder other than `./plugins`.
`opsai plugin remove <id>` deletes a plugin. After either command, restart the tools and kb services so they pick up the
change.

Compose mounts the checkout's `plugins/` read-only at `/plugins` in the tools and kb containers, and
`OPS_PLUGINS_HOST_DIR` names another host folder. So for a Compose install, running `opsai plugin install --into <that
folder>` and restarting both services is the whole installation.

The tools and kb services load every plugin when they start. A plugin that fails validation is left out and logged at
start as `plugin_failed` with its error, and every other plugin still loads.

### Plugins in a built image

The release image can carry plugins of its own, in `/app/plugins`, which is its `OPS_PLUGINS_DIR`. It bakes in the
plugins that the file `deploy/plugins.json` pins, and that list is empty today, so a release image holds no plugin until
you install one or mount a folder at `OPS_PLUGINS_DIR`. Each pin names a GitHub repository, a full commit, the plugin's
folder in it and the sha256 digest of that folder:

```json
{"source": "https://github.com/chanl-ai/ops-ai-plugins", "ref": "<40-character commit>", "path": "plugins/salesforce",
 "sha256": "<64-character digest>"}
```

The image build fetches each commit as a tarball, checks the plugin folder against its digest before it installs
anything, validates the plugin as `opsai plugin install` does, and stops on any problem. A pin with no digest, or a
download whose folder differs from its digest, stops the build, so a swapped or altered archive never reaches an image.
The digest covers each file's path and bytes rather than the archive, so it does not change when GitHub recompresses a
tarball. A branch or tag is refused, so an image built twice from the same commit holds the same plugins.

To ship a newer plugin, run `make plugins-bump`, which writes the commit and the digest together. Review the plugin's
change between the two commits and rebuild the image. To bake the pinned plugins into a folder yourself, run
`uv run python deploy/images/bake_plugins.py --into ./plugins`.

### Keep a laptop and a cloud box on the same plugins

`deploy/plugins.json` is the one list of plugins for the image, a laptop and a cloud box. These commands keep the
plugins folder equal to that list:

| Command | What it does |
|---|---|
| `make plugins-sync` | Puts the pinned plugins into `OPS_PLUGINS_DIR` (by default the main checkout's `plugins/`). Plugins that are already there and were not put there by this command move to `plugins.bak-<date>/`, and are never deleted. `make box-up` runs it in a box |
| `make plugins-sync PLUGINS_DEV=../ops-ai-plugins` | Links the plugin folders of a working copy instead of the pinned commit, so an edit shows after the next restart. Run `make plugins-sync` without `PLUGINS_DEV` to go back to the pinned ones |
| `make plugins-bump` | Moves every pin to the current main of the plugins repository and prints the old and new commit for each plugin. `REF=<branch\|tag\|sha>` moves to that instead. The file always records the full commit and the plugin folder's sha256 digest at it |

Restart the tools and kb services after a sync. The staging deploy (`make stg-deploy`) checks the running app. The
plugins in its `OPS_PLUGINS_DIR` must match `deploy/plugins.json` by id and version, or the deploy fails (see
[Fly staging](../deploy/fly-staging.md)).

## Turn a plugin on

Until you install a plugin, there is nothing to turn on. The plugin routes answer 404, and the kb service refuses a plugin
source with `tools_unavailable`. Once a plugin loads, every team is offered it. The platform admin decides which plugins
are installed, and withdraws one by taking it out of the plugins folder.

Each team turns the app on in the console, in the app's Connect window, where it also sets its settings and signs in
([Apps](apps.md#turn-an-app-on)). The calls below do the same steps from a script.

Ops AI's own OAuth app for a plugin is used by every team that does not bring its own. It comes only from the install
config. Register the app once with the vendor and set its client in the deploy's secret store:
`OPS_PLUGIN_CLIENTS='{"opsai.salesforce": {"id": "<client id>", "secret": "<client secret>"}}'`. The tools service reads
it at start and never writes the secret to the database, and no route sets or shows it. A team's own client is kept once,
and the accounts that sign in with it point at that row.

| Who | Call | What it does |
|---|---|---|
| Platform admin | Install config `OPS_PLUGIN_LOCKED='{"opsai.salesforce": {"api_version": "61.0"}}'`, then restart the tools service | Fixes a lockable setting for every team. Taking the plugin out of the plugins folder stops every team's calls, which then read "isn't installed on this system" |
| Team admin (`connections.manage`) | tools service `PUT /v1/apps/plugin:opsai.salesforce/team` with `{enabled, settings, signIn, kind, credentials, clientId, clientSecret}` | Turns the app on for the team and makes the team's default account, whole, for its sign-in kind (below). Turning it off again keeps the account and settings |
| Team admin | `POST /v1/apps/plugin:opsai.salesforce/accounts` with `{name, sandbox: true, ...}` and the same sign-in fields | Adds a sandbox account, such as a Salesforce sandbox org. Test runs use it and live runs never do. Its sign-in address and the instance its sign-in names are its own |
| Security | Nothing to list for the plugin's own hosts | The hosts in the manifest's `egress` (filled in with the team's settings) are reached by that plugin's sign-in, token, test and tool requests without being listed. No other call reaches them unlisted. Private, loopback, link-local and metadata addresses stay refused |
| Team admin | `POST /v1/apps/plugin:opsai.salesforce/accounts/{id}/sign-in`, then `POST /v1/sign-ins/complete` | Signs the team in. Settings marked `from_token` are read from the token answer here and kept on that account |

The first time a team admin turns the app on, one call creates the account, whatever kind of sign-in the plugin uses. `kind` picks one of the plugin's
`connection.kinds` (the first when left out) and cannot change once the account exists (`kind_fixed`). `credentials`
holds the kind's own fields. A key is sealed and never answered back, and a later turn-on that sends one part replaces
only that part. Test connection reads the manifest's `health_check` for every kind.

| Kind | `credentials` | What the tools service adds to each call |
|---|---|---|
| `none` | Nothing | Nothing |
| `api_key` | `key` | The key, in the header or query parameter that `connection.api_key` names |
| `basic` | `username`, `password` | `Authorization: Basic` |
| `bearer` | `token` | `Authorization: Bearer` |
| `oauth2_client_credentials` | None, with `clientId` and `clientSecret` beside it, or the platform's app | A token from `token_url`, fetched and renewed by the tools service |
| `oauth2_auth_code` | None, with the OAuth app as above | The team's or each person's token after they sign in |
| Either OAuth kind, where the app proves itself with its certificate | `clientAuth: private_key_jwt`, `signingCertificate` and `signingKey`, with `clientId` beside it and no client secret | A token asked for with a client assertion signed by the key (RFC 7523), on every token request, refresh, sign-in and disconnect. Microsoft Entra apps at banks use this |
| `oauth2_jwt_bearer` (a signed service account) | `signingKey`, and optionally `signingCertificate`, `subject`, `audience` and `scopeIn` (`form` or `claim`). `clientId` is the issuer | A token whose grant is a JWT signed by the key, and signed again when it expires. DocuSign uses it (client id is the integration key, `subject` is the user id, `audience` is `account-d.docusign.com`), and so does Google (client id is the service account email, `scopeIn` is `claim`) |
| Any kind | `clientCertificate`, `clientKey` and `trustedCa` | The client certificate on the TLS handshake. A refused handshake fails with `TLS_FAILED` |

A wrong key, password or token fails Test connection with the system's 401, and a call with it fails with
`UPSTREAM_ERROR` 401. A wrong client secret fails the token fetch with `AUTH_FAILED` and marks the connection
`needs_reconnect`. A Python tool's answer is scrubbed of the connection's credential, as a data tool's is.

The signing key and certificate are their own pair, separate from the mTLS `clientCertificate` and `clientKey`, so the
signing key is never offered on a TLS handshake. Saving a key that does not belong to its certificate is refused, naming
both, even when only one half changes. Every read shows the certificate's SHA-256 thumbprint, subject and expiry, and
whether it expires within 30 days. It never shows the key. A certificate past its expiry is refused before any token
request, as `AUTH_FAILED` "the signing certificate expired on <date>", and marks a team connection `needs_reconnect`.
When the system refuses an assertion itself (another key, a replay), the result is `AUTH_FAILED` naming its host and
error, and it is never retried with a secret. RS256 (RSA keys) and ES256 (P-256 keys) are the supported algorithms, and
any other key is refused.

### Who signs in

A team that gives `clientId` and `clientSecret` signs in with its own OAuth app, and one that gives neither uses the
platform's. `signIn` is either `team` or `person`. With `team`, one team login is used for every call (the console shows
it as "Everyone uses the team's login"). With `person`, each person signs in with their own login, from the chat card or
My apps, and calls act as them. A plugin lists which of these it allows. The team login is never a backup for each
person: `person_or_team` and `teamBackup: true` are refused, and an account stored with them reads as `person`. One
team's app, connection or token never serves another team, and one person's token never serves anyone else.

On a connection that each person signs in to, a key, password or token kind asks each person for their own. The team
gives the address and how the key is sent, but no key of its own. A person gives theirs with
`PUT /v1/me/accounts/{id}/credentials` and `{credentials: {key}}` (`{username, password}` for `basic`, `{token}` for
`bearer`), from the chat card that asks for it or from My accounts. It is sealed in their own row and never answered
back. `GET /v1/me/accounts?every=true` lists every account of the team that a person can connect, with `connected`, the
method and the fields to give. A call acting for a person who has no key is refused with `CONNECTION_NOT_LINKED`, naming
`authKind` and `personFields`, so the console asks for the key in place. A call with nobody behind it is refused with
reason `no_person`. A wrong key fails only that person's call and leaves everyone else's working, and Disconnect removes
it.

### Use several accounts of one app

A team can keep several named accounts of one app, such as two Salesforce orgs or two GitHub servers. Each account has a
name that no other account of the app in the team holds, ignoring case and spaces. Two adds at the same moment make one
account, and the other is refused with 409 `account_name_taken`.

| Who | Call | What it does |
|---|---|---|
| Whoever holds `connections.manage` | `POST /v1/apps/{app}/accounts` with `{name, settings, makeDefault}` | Adds a live account that signs in where its `settings` say, at its own sign-in address. `makeDefault` makes it the team's default. A test account cannot be the default |
| Any member | `POST /v1/me/accounts/{id}/another` with `{name, settings}` | Adds a second account of their own, signing in where `settings` say. It only works for apps that sign in with an account. With no body, it is named "<person>'s other account" and signs in where `{id}` does |
| Any caller | `GET /v1/apps/{app}/accounts?usable=1&name=…&mine=1` | Lists the accounts a call may name, each with an `identity`. `usable` keeps the team's live accounts (what a workflow step or an agent names), `mine` adds the caller's own, and `name` keeps the one so named |
| A run | `POST /v1/calls` with `runContext.accounts: {appId: name}` | Each app's call uses the account named for its app. `runContext.account` (one name) is still read |
| A builder | An `ops.action.tool` step's `accounts` parameter, or an agent's `accounts` (`PATCH /v1/agents/{id}`) | The step's or agent's choice for each app. Publishing checks each one with the tools service and refuses 422 `account_name_unknown`, though a draft may name an account that is not made yet |
| A person | `PUT /chat/threads/{id}/connectors` with `{off, accounts}` | The chat's choice for each app, kept on the chat. `GET` lists each app's accounts when it has two or more, and the `account` in use |
| Deleting | `DELETE /v1/apps/{app}/accounts/{id}` | Refused with 409 `account_in_use` while a workflow draft or published version, or an agent, names the account. The details give `published`, `drafts`, `workflows` and `agents`. It is refused with 503 when the agents service cannot answer the count |
| Before a rename | `GET /v1/workflows/definitions/account-uses?app=…&name=…` | Counts the drafts and published versions that name the account. A rename rewrites none of them, so a published version is refused at its next call until its next publish names the new name |

The agents service sends what was chosen and never picks or compares names itself. A step's choice wins over a chat's,
and a chat's over the agent's. A call run with the team login keeps only the step's choice. The model is told which
account is in use and where it points, on its apps line ("Salesforce: on · uses EU org (kestrel-eu.my.salesforce.test)").
That line is read from the account's `pointsAt`, so a person's email never reaches the prompt, and the model has no tool
input that changes the account.

The tools service picks the account for each call as follows:

| Case | Account used |
|---|---|
| The call names an account for its app | That account of the call's team. An unknown name is refused with 404 `ACCOUNT_NOT_FOUND` and never falls back to the default |
| It names one person's own account | Only when the call acts for that person. Otherwise it is refused with 403 `ACCOUNT_NOT_YOURS`, so a step or schedule never signs in as someone |
| A test run names a live account | The app's test account. With none, the call is refused with 409 `SANDBOX_REQUIRED` |
| It names none and acts for a person with their own sign-ins | Their default. With two or more and none chosen, the result is `ACCOUNT_CHOICE_NEEDED` |
| Otherwise | The team's default |
| The named account's team sign-in ended (expired, refused or revoked) | None. The call answers 200 with `AUTH_FAILED` in its output, and the details name the account (`connection`) and `connectedEvent`. A run waits on that event ("Sign in to EU org again to continue"), a chat draws the sign-in card, and an admin's new sign-in reports the event so the run goes on. No other account is tried |

If an account's sign-in changes from `team` to `person`, a call acting for a person signs in as that person. A call
acting for nobody, such as a schedule, is refused with `CONNECTION_NOT_LINKED` and reason `no_person`.

Every account row, in the app's Accounts list and the account pickers, carries an `identity` that tells accounts apart.
A plugin's `connection.identity` names the settings to show. With none declared, the row shows what the sign-in filled,
then the account's own sign-in address, and for a custom app its address, with who signed in last. A second account that
points at the same place carries `samePlaceAs` with the first's name, which is a warning only. Each team row also carries
`signIn` (whose login its calls use, `team` or `person`) and `peopleSignedIn` (how many people hold their own sign-in on
that account). A member's Accounts tab lists the team's accounts and counts their own sign-ins (`me.signIns`).

In the console, an account row's Settings dialog changes the name, who signs in and the auth config, and the star on the
row makes it the team default. "Each person signs in" shows the count against the team's members, and a rename or a
change of who signs in first shows how many drafts and published versions name the account. A first turn-on through
Ops AI's own app keeps the sign-in address it asked for as a default on the auth config, so a second account may type its
own. A team whose first turn-on kept the address fixed keeps it fixed, and adds an auth config that holds the address as
a default for a second org.

### Package apps

A package app is a plugin whose tools run inside another app, such as a lending or life-sciences package installed in a
Salesforce org. It has no accounts of its own. Each call signs in with the chosen account of the app it runs on and
reaches that account's address. The manifest says so in `connection`:

| Field | What it does |
|---|---|
| `kinds: [none]` | Required with `runs_on`, because the package never signs in by itself |
| `runs_on` | The plugin id of the app it runs inside (`opsai.salesforce`). `endpoint`, `egress` and headers are filled in with that app's settings for the chosen account, so `{instance_url}` is the org's |
| `requires` | The objects the package installs in the app. Optional |
| `requires_check` | A path from `/`, with `{name}` for each required object, that answers 404 or 400 where the object is missing (`/services/data/v{api_version}/sobjects/{name}/describe`). Required with `requires` |

`opsai plugin validate` refuses `runs_on` with another kind, `runs_on` naming the plugin itself, `requires` without
`runs_on`, and a check path that names no object. Turning a package on for a team makes no account, and it is refused
with 400 `host_app_missing` when the install lacks the app it runs on.

| Case | What happens |
|---|---|
| A call names an account under the app it runs on (`runContext.accounts: {"plugin:opsai.salesforce": "EU org"}`) | The package's tool signs in with that account, chosen as that app's own calls choose one |
| A call names an account under the package's own app id | 404 `ACCOUNT_NOT_FOUND`, because the package has none |
| The app it runs on is off for the team, or not installed | 403 `APP_OFF_FOR_TEAM` naming that app, or `PLUGIN_DISABLED` |
| The chosen account's last Test found a required object missing | 409 `PACKAGE_MISSING` naming the account, before any request leaves the tools service |
| The account was never checked (it signed in before the package was installed) | The call runs, and its next Test records the check |

The check runs with every passing Test, which also runs after each sign-in. It reads each object's path through the
account's sign-in and saves `health.packages` on the account, by package id, with the objects missing.
`GET /v1/apps/plugin:{package}/accounts` lists the accounts of the app it runs on, each with `appId` (the key a step or
agent names it under) and `missingObjects`, so a picker can show an account as unavailable.

After that, builders grant the plugin's tools to agents like any other tool, and a knowledge base adds a source with
`POST /v1/sources` and `{type: "tool", config: {plugin: "opsai.salesforce", source: "articles"}}`. Nobody can edit,
publish or delete the plugin's tool module, and a new plugin version replaces it.

## Update an installed plugin

Updating is behind the `plugin_updates` install flag (`OPS_FLAGS`), which is off by default. While it is off, a plugin's
tools are written once and every team calls the installed manifest. When it is on, each team runs the plugin version it
took:

| What | How |
|---|---|
| The team's version | Its binding records the version, a digest of the tool declarations (the plugin-wide headers and each tool's manifest entry) and the declarations themselves. A team takes the installed version when it turns the plugin on |
| An upgrade | The operator installs the new package and restarts the tools service. The account's tool row follows it, keeping each tool's id and keeping a dropped tool as a switched-off row. Nothing changes for a team until it takes the update |
| Calls and lists | They are built from the team's version. A changed tool keeps its request and inputs, a dropped one still answers and stays listed, and a new one is neither listed nor callable. A Python tool always runs the installed package's function |
| The review | `GET /v1/apps/plugin:{id}/update` shows both versions, and each new, changed and removed tool with its inputs added, removed and changed. `GET /v1/tool-uses?tools=` on the agents service names the team's agents and workflows that use each one |
| Taking it | `POST /v1/apps/plugin:{id}/update` with the installed digest that the review was read at. If another upgrade has happened since, it answers 409 `update_changed`. Keeping the current version is not taking the update |

The sign-in (addresses, scopes and the lookup after sign-in), the endpoint and the egress hosts are not versioned per
team. They are always the installed version's.
