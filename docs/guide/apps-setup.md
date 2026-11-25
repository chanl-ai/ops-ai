# Set up an app

Status: current. The steps a team admin takes to turn an app on, sign it in, bring the team's own OAuth app, and turn it
off. What apps, tools and accounts are: [Tools and apps](apps.md).

## An app's state

Every App card, on the Apps tab and at the top of the App's page, shows one state. The App's Settings read the same
state, and each state has one next action.

| State (`appState` in the API) | When | What a team admin does | What a member sees |
|---|---|---|---|
| Connected (`connected`) | On, and its Account signed in | Nothing to do | Nothing to do |
| Signed in, test failed (`test_failed`) | On; the test after the sign-in failed | **Reconnect** | The failure |
| Needs sign-in (`needs_sign_in`) | On; the team's Account, or your own on an App each person signs in to, has not signed in | **Connect** | **Sign in from Mine** |
| Auth config needs fixing (`auth_config_broken`) | On for the team, but the auth config its Account signs in through is gone or has no client secret, and the team has no other | **Fix the auth config** (add or repair one, then sign in again); **Turn off** stays in Settings | Ask an admin |
| Needs an auth config (`needs_auth_config`) | Off for the team, and the App signs in through an auth config the team does not have | **Add an auth config**, which opens the new auth config for that App and signs nobody in | Ask an admin |
| Available (`off`) | Installed, and not on for the team: never turned on, or turned off | **Turn on** | Ask an admin |
| Not installed (`not_installed`) | The system does not hold this App's plugin and the team never had it on | Nothing; the person who runs Ops AI at your company installs Apps | The same |
| No longer installed (`removed`) | The team had it on; the system no longer holds its plugin | **Delete app** removes what it left | The same |

Beside `appState`, the API answers `appGroup`, who acts next: `on` (it works), `needs_you` (the caller's own sign-in),
`needs_admin` (someone who manages the team's apps) or `gone`. The App's page, the Apps tab, My connectors and the chat
picker group and act on it; none works it out again. On an App each person signs in to, a person's state is their own
sign-in, and an auth config's name and id are shown only to builders and admins.

> [!NOTE]
> `off` means installed and not on for the team; `not_installed` means the plugin itself is missing. Earlier versions
> answered `not_installed` for both, so code that matched it for an App that is off should match `off`.

## Turn an app on

Turning an App on for the team and connecting an account are two separate actions. Turning it on saves the team's
setting and opens no sign-in; connecting is its own button, and it is optional for the admin who turned the App on.

| Step | What happens |
|---|---|
| 1. On **Apps › Team setup**, press **Turn on** on the App's card (the App's page has the same button) | The Turn on window opens for an App that asks for something, such as a key or a place to sign in. An App that asks for nothing (a template pack such as Core, or Website) turns on at once, with no window, and the card reads Connected |
| 2. For an App that asks where you sign in (Salesforce), pick the place: login.salesforce.com, test.salesforce.com, or your company's address (My Domain), typed as its host | Saved on the App's auth config |
| 3. Pick whose account Tools use: each person's, the team's, or each person's with the team's for runs nobody started | Asked once, when the App is first turned on |
| 4. Keep **Give the team's assistant this app's read tools** ticked, or untick it | The assistant gets the read Tools when the App is saved |
| 5. Press **Turn on** | The team's setting is saved and no sign-in window opens. The window reads, for example, **Saved. Salesforce is on for Operations**, how many read Tools were added, and **Members connect their own account from Apps › Mine** |
| 6. Optional: press **Sign in with my login**, or **Sign in the team login** when everyone uses the team's login | The App's own sign-in page opens; allow access there, and the window names the account that signed in |

A template pack (Core, Starter skills) is not listed on Apps, because nobody connects an account to it. Open its page to turn it on or off: the empty template list on a page such as Skills links to it, and **Turn off** there opens the same window as for any App.

An App is **Connected** only once an Account has signed in or a test has passed; saving settings alone does not count.
The same rule holds everywhere an App's settings are saved: **Settings › Set up**, a new auth config and the Turn on
window each save and stop, and never start a sign-in. A sign-in starts only from a button that says Connect or Sign
in: **Connect** on the App's page once it is on, **Sign in** on an Account's row, or **Connect** on **Apps › Mine**.

A member who opens an App the team has not turned on, from **Apps › Mine**, reads **Not set up for your team
yet** with the admins to ask, and stays on Mine. Only someone who may turn the App on is offered **Turn on**, which
opens the App's page.

**Add account** works on an App with no Account yet: the first Account becomes the default. A team admin turns an App
on and connects the team's Accounts.

### The first time a team turns on a plugin's app

An App a plugin brings ([plugins guide](plugins.md)) needs two things before its card offers Connect, and its first
Connect window asks for more than the steps above.

| Who | What | Where |
|---|---|---|
| Platform admin | Installs the plugin (its folder in the plugins folder, or pinned in the image); it is then offered to every team. Settings fixed for every team come from the install config | The install's plugin settings ([plugins guide](plugins.md)) |
| Security admin | Lists the App's hosts, so its sign-in and calls may leave | **Settings › Security › Egress**, Add host (and Add range for a host on a private network) |
| Team admin | Presses **Turn on** | The window shows the App's settings (such as its API address), whose account calls use (the team's, each person's, or each person's with the team's as backup), the OAuth app (Ops AI's, or your own with its client ID and secret and the return address to register), and its sign-in address. **Turn on** saves them and opens no sign-in; **Connect my account** or **Connect the team account** after it opens the App's sign-in page |

The App's page is **Data › Apps** then the App's name, at `/integrations/apps/plugin:<plugin id>`. One Connect is
enough to use it everywhere: test runs and live runs both sign in with the account you connected.

## Auth configs and secrets

An App's **Auth configs** tab lists the OAuth app each App signs in with: **Ops AI**,
kept by Ops AI, or your team's own app. To bring your own app (a Salesforce connected app, a GitHub OAuth app):

| Step | Where |
|---|---|
| 1. Copy the **Callback URL** Ops AI shows | **New auth config**, **Edit**, and the auth config's row on the App's page |
| 2. Register it as the callback URL of your app at the system | Salesforce: the connected app's Callback URL. GitHub: the OAuth app's Authorization callback URL |
| 3. Enter the app's client ID and secret in Ops AI | **New auth config** or **Edit**; the secret is sealed and only its last four characters are shown |

A Salesforce app needs the **Manage user data via APIs (api)** and **Perform requests at any time (refresh_token,
offline_access)** scopes; without the second, people are signed out when the first token ends.

Ops AI builds the callback URL from its console address (`OPS_CONSOLE_URL`), so it must match the address people open.
Changing the client ID or permissions makes the accounts on it sign in again.

**Data › Secrets** lists the values Tools send, such as an API key in a header. A value is encrypted, never shown
again, and removed from whatever an App answers. A Security admin adds, rotates and deletes Secrets.

## A run waiting for a person

When a workflow acts for a person who has not signed in to an App each person signs in to, the run waits instead of
failing. **Human Tasks** shows a task, **Sign in to <App> to continue**:

- The person it waits for presses **Sign in to <App>**. Once they have signed in, the run goes on by itself. They are
  never asked to choose between their own login and the team's: that is the App's setting.
- Where the App has a team login, someone else allowed to run as it (team admins by default) can press **Run with the
  team login**, and the step goes on with it.

## Turn an app off

On the App's **Settings**, **Turn off** stops the App's Tools for your team. The window lists every agent and workflow
that uses its Tools before anything stops. The App's Accounts and the Resources you added stay. The App then reads **Available** in its
header and its Settings, and **Turn on** there puts it back as it was, with no window and no sign-in.

## Next

<!-- site: cards -->
- **[Tools and apps](apps.md)**: apps, tools, accounts and approvals.
- **[Install and turn on a plugin](plugins-install.md)**: add an app the catalog does not have yet.
- **[Human tasks and approvals](human-tasks.md)**: make an app's writes wait for a person.
