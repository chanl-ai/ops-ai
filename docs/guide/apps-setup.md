# Set up an app

Status: current.

An agent can only use a system after a team admin has turned that system's app on and someone has signed in to it. When
a card says **Needs sign-in** or **Available**, an agent that depends on the app fails or waits, and a person is left
asking in a chat why nothing happened. This page is for the team admin. It shows how to turn an app on, how to sign it
in, how to bring your own OAuth app, and how to turn the app off again. For what apps, tools and accounts are, see [Tools
and apps](apps.md).

## Get an app working for your team

<!-- site: steps -->
1. **Turn the app on.** Press **Turn on** on its card and answer the questions the window asks.
2. **Sign in.** Press **Sign in the team login**, or leave each person to sign in from **My apps**.
3. **Check the state.** The card reads **Connected** once an account has signed in and its test has passed.
4. **Fix what the card names.** Every other state has one next action, listed below.

## An app's state

Every app card, on the **Apps** page and at the top of the app's own page, shows one state. The app's **Settings** tab
reads the same state, and each state has one next action.

<!-- site: state caption="An app from installed to connected, and where it can fall back" -->
- **Available**: Installed and not on for the team
  - **Needs sign-in**: A team admin presses **Turn on**
- **Needs sign-in**: On, with no account signed in yet
  - **Connected**: Someone signs in and the test passes
  - **Signed in, test failed**: The sign-in worked and the test failed
- **Signed in, test failed**: The failure is shown to members
  - **Connected**: A team admin presses **Reconnect** and the test passes
- **Connected**: The app works for the team
  - **Available**: A team admin presses **Turn off**

| State (`appState` in the API) | When | What a team admin does | What a member sees |
|---|---|---|---|
| Connected (`connected`) | The app is on and its account has signed in | Nothing to do | Nothing to do |
| Signed in, test failed (`test_failed`) | The app is on, and the test after the sign-in failed | **Reconnect** | The failure |
| Needs sign-in (`needs_sign_in`) | The app is on, but the team's account, or your own account on an app where each person signs in, has not signed in | **Connect** | **Sign in** from **My apps** |
| Auth config needs fixing (`auth_config_broken`) | The app is on for the team, but the auth config its account signs in through is gone or has no client secret, and the team has no other | **Fix the auth config** by adding or repairing one and signing in again. **Turn off** stays in Settings | Ask an admin |
| Needs an auth config (`needs_auth_config`) | The app is off for the team, and it signs in through an auth config the team does not have | **Add an auth config**, which opens the new auth config for that app and signs nobody in | Ask an admin |
| Available (`off`) | The app is installed and not on for the team, either because it was never turned on or because it was turned off | **Turn on** | Ask an admin |
| Not installed (`not_installed`) | The system does not hold this app's plugin, and the team never had it on | Nothing. The person who runs Ops AI at your company installs apps | The same |
| No longer installed (`removed`) | The team had it on, and the system no longer holds its plugin | **Delete app** removes what it left | The same |

The API also returns `appGroup`, which says who has to act next. `on` means the app works. `needs_you` means you have to
sign in yourself, and `needs_admin` means someone who manages the team's apps has to act. `gone` means the app's plugin is
no longer installed. The app's page, the **Apps** page, **My apps** and the chat picker all read this one value, so they
always agree. On an app where each person signs in, the state you see is your own sign-in. Only people who may manage the team's
apps, which means admins by default, see an auth config's name and id.

> [!NOTE]
> `off` means the app is installed and not on for the team, and `not_installed` means the plugin itself is missing.
> Earlier versions answered `not_installed` for both, so code that matched it for an app that is off should now match
> `off`.

## Turn an app on

Turning an app on for the team and connecting an account are two separate actions. Turning it on saves the team's setting
and opens no sign-in. Connecting is its own button, and the admin who turned the app on does not have to press it.

| Step | What happens |
|---|---|
| 1. On **Apps › Team setup**, press **Turn on** on the app's card. The app's page has the same button | An app that asks for something, such as a key or a place to sign in, opens the Turn on window. An app that asks for nothing, such as a template pack like Core or Website, turns on at once with no window, and its card reads Connected |
| 2. For an app that asks where you sign in, such as Salesforce, pick the place: login.salesforce.com, test.salesforce.com, or your company's address (My Domain) typed as its host | The choice is saved on the app's auth config |
| 3. Pick who signs in: **Everyone uses the team's login** or **Each person signs in** | Asked once, when the app is first turned on |
| 4. Keep **Give the team's assistant this app's read tools** ticked, or untick it | The assistant gets the app's read tools when the app is saved |
| 5. Press **Turn on** | The team's setting is saved and no sign-in window opens. A message reads, for example, **Saved. Salesforce is on for** and your team's name, with how many read tools were added and where members connect their own accounts |
| 6. Optional: press **Sign in with my login**, or **Sign in the team login** when everyone uses the team's login | The app's own sign-in page opens. Allow access there, and the window names the account that signed in |

A template pack, such as Core or Starter skills, is not listed on **Apps**, because nobody connects an account to it. Open
its page to turn it on or off. The empty template list on a page such as **Skills** links to it, and **Turn off** there
opens the same window as for any app.

An app reads Connected only after an account has signed in or a test has passed. Saving settings is not enough. That holds
wherever you save an app's settings: its **Settings** tab, a new auth config, or the Turn on window. Each one saves your
changes and starts no sign-in. A sign-in starts only from a button labelled Connect or Sign in. Those are **Connect** on
the app's page once the app is on, **Sign in** on an account's row, and **Connect** on **My apps**.

A member who opens an app that the team has not turned on, from **My apps**, reads **Not set up for your team yet** with
the admins to ask, and stays on **My apps**. Only someone who may turn the app on is offered **Turn on**, which opens the
app's page.

A team admin turns the app on and then connects the team's accounts. You can press **Add account** even before the app has
any account, and the first account you add becomes the default.

### The first time a team turns on a plugin's app

An app that a plugin brings ([plugins guide](plugins.md)) needs two things before its card offers Connect. Its first
Connect window also asks for more than the steps above.

| Who | What | Where |
|---|---|---|
| Platform admin | Installs the plugin, either as its folder in the plugins folder or pinned in the image. It is then offered to every team. Settings that are fixed for every team come from the install config | The install's plugin settings ([plugins guide](plugins.md)) |
| Security admin | Lists hosts that the app's own manifest does not name, such as a website a person adds as a source, and adds a range for a host on a private network | **Settings › Security › Egress**, **Add host** and **Add range** |
| Team admin | Presses **Turn on** | The window shows the app's settings, such as its API address, who signs in, the OAuth app (Ops AI's, or your own with its client ID, secret and the return address to register) and its sign-in address. **Turn on** saves them and opens no sign-in. **Sign in with my login** or **Sign in the team login** afterwards opens the app's sign-in page |

To find the app's page, open its card on **Data Gateway › Apps**. You only need to connect once, because test runs and live
runs both sign in with the account you connected, unless the app has a sandbox account, which test runs use.

## Auth configs and secrets

An auth config is the saved OAuth app, with its client ID and secret, that an app signs in through. An app's **Auth configs** tab lists them. It is either **Ops AI**, kept by Ops AI, or
your team's own app. To bring your own app, such as a Salesforce connected app or a GitHub OAuth app, follow these steps.

| Step | Where |
|---|---|
| 1. Copy the **Callback URL** that Ops AI shows | **New auth config**, **Edit**, and the auth config's row on the app's page |
| 2. Register it as the callback URL of your app at the system | Salesforce: the connected app's Callback URL. GitHub: the OAuth app's Authorization callback URL |
| 3. Enter the app's client ID and secret in Ops AI | **New auth config** or **Edit**. The secret is sealed, and only its last four characters are shown |

A Salesforce app needs the **Manage user data via APIs (api)** and **Perform requests at any time (refresh_token,
offline_access)** scopes. Without the second, people are signed out when the first token ends.

The callback URL is built from the address people open Ops AI at. If your OAuth app rejects it, ask whoever runs Ops AI to
check that address. Changing the client ID or the permissions makes the accounts on it sign in again.

**Data Gateway › Secrets** lists the values that tools send, such as an API key in a header. A value is encrypted, never
shown again, and removed from whatever an app answers. A team admin adds, rotates and deletes secrets, or the Security team when your policy says so.

## A run waiting for a person

When a workflow acts for a person who has not yet signed in to an app where each person signs in, the run waits instead
of failing. **Human Tasks** shows a task called **Sign in to <App> to continue**.

- The person the run waits for presses **Sign in to <App>**. Once they have signed in, the run goes on by itself. They are
  never asked to choose between their own login and the team's, because that is the app's setting.
- Where the app has a team login, someone else who is allowed to run as it (team admins by default) can press **Run with
  the team login**, and the step goes on with it.

## Turn an app off

On the app's **Settings** tab, **Turn off** stops the app's tools for your team. Before anything stops, the window lists
every agent and workflow that uses the app's tools. The app's accounts and the resources you added stay. The app then reads
**Available** in its header and its Settings, and **Turn on** there puts it back as it was, with no window and no sign-in.

## Next

<!-- site: cards -->
- **[Tools and apps](apps.md)**: apps, tools, accounts and approvals.
- **[Install and turn on a plugin](plugins-install.md)**: add an app that the catalog does not have yet.
- **[Human tasks and approvals](human-tasks.md)**: make an app's writes wait for a person.
