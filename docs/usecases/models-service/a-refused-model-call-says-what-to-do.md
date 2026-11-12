# A refused model call in chat says what went wrong with the provider and what to do, worded for an admin or a member

Status: passing. Id: `uc-720`. Service: `models-service`. Layers: ui.

When the provider behind an agent's model refuses the call, the reply's error names the cause (the key was refused,
the provider could not be reached, it limited calls, it failed) and the next step for whoever reads it: an admin who
manages settings is told to fix it on Settings > Model providers and offered the page; anyone else is told to ask an
admin. The provider's own body, which can echo the key, is never shown. The codes and statuses are listed in
`docs/services/models-service/overview.md` "Provider failures".

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| The run's demo stack | the runner starts platform sign-in, agents-service, models-service and the fake OpenAI, which refuses any credential but the stub `FAKE_OPENAI_KEY` (`packages/usecase-runner/src/harness.ts`) |

The script saves a wrong value for model provider key `OPENAI` as the account admin and points connection
`openai-local`, which serves the agents' `default` alias, at it. No real model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru, an admin who manages settings, asks the default agent a question in chat | The reply stops with "The model provider refused the account's key. Check or replace the key on Settings > Model providers." and an Open Model providers link; the wrong key's value is nowhere on the page |
| 2 | She reloads the conversation | The same sentence and link |
| 3 | Ravi, a viewer of Operations, asks the same in his own chat | "… Ask an admin to check the key on Settings > Model providers." and no link |
| 4 | Both at 1440 and 390 wide | The same text; the page does not scroll sideways |

## Acceptance layers

| Layer | Script | Proves |
|---|---|---|
| ui | `scripts/test-uc-720-ui.mjs` | Steps 1 to 4 in a real browser, screenshots per role and width in the run's evidence folder |

## Non-vacuous check

`1 an admin reads that the provider refused the key and is offered Settings > Model providers` and `3 a member is told to
ask an admin and is not offered the settings page`: with the message view showing the service's message instead of the
console's wording for the code, both fail (seen: the same sentence for both readers and no link).
