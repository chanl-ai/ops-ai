# A write runs only after as many people as its policy names approve it

Status: passing. Id: `uc-049`. Service: `agents-service`. Layers: api. Card: c-048 (T005).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| agents-service on the scripted model, with tools-service as its gateway | started by the script on the run's own ports |
| A bank system on https | the fake bank (`lib/fake_bank_https.py`), listed on egress with its private range |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A draft module with one write on the fake bank; `PATCH` its operation to `approvers: 2`; Security approves the review | 200; `GET /v1/tools/{name}` answers `approval.approvers` 2 |
| 2 | Grant the write to a new agent, publish it, and have the scripted model call it in chat | the turn stops on an approval card |
| 3 | Maya approves | 200, state `awaiting_second`; the fake bank receives nothing |
| 4 | Maya approves again | refused; still nothing at the bank |
| 5 | Priya approves | 200, state `approved`; the bank receives the POST once |
| 6 | `GET /v1/executions?tool=` | one row, allowed and ok |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-049-api.py` | passing |

## Non-vacuous check

Step 1's policy check was seen failing (`approvers` 1) while a draft module's edit kept a baseline taken before the
edit; steps 3 to 5 then failed with the write running on the first approval. OPA refusing a token naming one person
under `approvers: 2` is `test_calls.py::test_a_write_whose_policy_needs_two_approvers_refuses_a_token_naming_one`,
seen failing with the rule removed.
