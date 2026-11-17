# An agent answers from a knowledge source with a citation, in mock and real mode

Status: current. Id: `uc-752`. Service: `agents-service`. Layers: api, sdk, ui.

Short title: An agent answers from a knowledge source with a citation, in mock and real mode

## Story

As a person who asks an agent a policy question, I want the answer to cite its source so that I can check it.

## People

| Person | Role | Does what |
|---|---|---|
| James Richardson | builder | Asks the agent and opens the citation |

## In this example

In this example a person asks the fraud agent the daily wire limit. The agent holds the fixture Wire Transfer Policy and answers with [1], which names the policy and its section 4.2.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A person asks and the answer cites the policy section | api | 2, 3 | 2 |
| S2 | The same chat through the SDK cites too | sdk | 2, 3 | 2 |
| S3 | The chat draws the citation and opens its source passage | ui | 2, 3 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Mode switch

`MODE=mock` (default): the scripted model and the fixture knowledge source. `MODE=real` (needs `APPROVED_REAL_CALLS` of 1 to 40, with the model key from the secrets manager): a real model alias and a website knowledge source. Real mode is **not built yet**: the scripts read `MODE` (`lib/main_chains.py`) and loosen only the answer wording; the website source and real alias wiring are open.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | An agent with no knowledge is asked the question | The answer carries no citation |
| 2 | The fraud agent on `kb_people` is asked | A citation [1] names Wire Transfer Policy, 4.2 Daily limits |
| 3 | The answer text | Carries $25,000 and the [1] marker (real mode: any of the key words and the marker) |
| 4 | The thread is read back | The stored reply keeps the citation and the scripted model (real mode: a real model) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-752-api.py` | passing |
| sdk | `agents-service/scripts/test-uc-752-sdk.py` | passing |
| ui | `agents-service/scripts/test-uc-752-ui.mjs` | passing |

## Non-vacuous check

Step 1 pairs with step 2: an agent without knowledge answers the same question with no citation, so a citation can only come from kb-service. Seen failing in the first run, before the pair used an agent that holds no knowledge.
