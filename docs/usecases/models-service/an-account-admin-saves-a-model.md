# An account admin saves a model provider key on Settings and a model call signs in to the provider with it; no other person sees or sets one

Status: passing. Id: `uc-532`. Service: `models-service`. Layers: ui. Card: an earlier change.

Model provider keys belong to the account (2026-10-27): an account admin (an admin on the Security team) saves
them on Settings > Workspace > Model providers, models-service keeps them sealed in its own `provider_keys` table and is
the only reader, and no team sees one.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| The run's demo stack | the runner starts platform sign-in, models-service and the fake OpenAI, which refuses any credential but the stub `FAKE_OPENAI_KEY` (`packages/usecase-runner/src/harness.ts`) |

The script makes provider connection `openai-uc532` at the fake's URL naming key `OPENAI`, and alias `uc532-mini` on
model `gpt-4.1-mini` through it, with agents-service's dev service token. Calls use agents-service's dev model key. No
real model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Call the alias before any key is saved | 503 `provider_key_missing` naming `OPENAI`; the provider is not called |
| 2 | Sam opens Model providers, adds `OPENAI` with the stub key, and the alias is called | The page lists `OPENAI` without its value; the call answers 200 with the fake's text; the API's list holds no value |
| 3 | Sam replaces the value with a wrong key, calls, then puts the stub back and calls | 502 `provider_error` (the fake refused the credential), then 200; the key is at version 3 |
| 4 | Delete `OPENAI` while the connection names it | 409 `key_in_use` |
| 5 | James, a builder of Operations, opens the page and tries the API | The page says only an account admin sees keys and shows no key; list and save answer 403; calls still answer |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `models-service/scripts/test-uc-532-ui.mjs` | passing, `make usecase-test UC=uc-532 LAYER=ui` (2026-10-28) |

## Non-vacuous check

Step 3, `a replaced value is what reaches the provider`: the fake answers only the stub key, so a key that never reached
the provider would look the same as one that did. With the fake started without `FAKE_OPENAI_API_KEY` (it then answers
any credential), the wrong key answered 200 and step 3 failed (seen 2026-10-28). Step 1 guards the other direction: with
the missing-key refusal removed, the call went to the provider with no key and models-service's own test failed
(`services/models-service/tests/test_provider_keys.py`).
