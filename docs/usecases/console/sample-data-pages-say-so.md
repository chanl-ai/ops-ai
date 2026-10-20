# A page on sample data says so and cannot be saved

Status: current. Id: `uc-125`. Service: `console`. Layers: ui.

Card c-173: 14 settings looked saved and reverted on reload because the console keeps them in the mock API (account,
sign-in, notifications, webhooks, API keys, gate policies, connection setup). Each such page or section now shows
"Sample data, changes aren’t saved", switches off every control inside it (Save, add, delete, switches) and never claims
"Saved as version N". Gate policies also carries the Preview badge. Source settings follow the stack: kb-service stores
them when it is configured, so only on the mock do they take the notice.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | Sam Adeyemi (Security admin); password `northfield-demo` |
| files-service | the ui harness's default stack, for the live setting |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1-2 | Sam opens Account, Security, Notifications, Sign-in, Webhooks, API keys and Gate policies | each shows the notice, and no button or field inside its gate is enabled |
| 3 | He opens Gate policies, then the Reviews queue | Preview in the first header, none in the second |
| 4 | He tries to tick a notification route (forced click, then Space), then reloads | no Save bar, no "Saved as version", no write sent, same value after the reload |
| 5 | He clicks a webhook row | nothing opens |
| 6 | He changes Storage's signed link lifetime, saves, reloads | "Saved as version", the new value after the reload, no notice on the page |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-125-ui.mjs` | passing |

## Non-vacuous check

Step 4 and the sweep in steps 1-2 go red when `SampleDataGate` renders no disabled fieldset (the controls are enabled and
the forced click opens the Save bar). Step 3 goes red without the `/settings/policies/gates` entry in `AREAS`. Step 6 is the
paired success: it fails if the live path stopped persisting.
