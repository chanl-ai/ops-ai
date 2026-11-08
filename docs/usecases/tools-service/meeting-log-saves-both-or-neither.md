# An advisor's meeting log saves the opportunity and its note together, or neither

Status: current on feat/assistant-routing-from-data behind the `OPS_PLUGINS` switch. Id: `uc-668`.
Service: `tools-service` with platform-service. Layers: api.
Design: the Salesforce plugin's opportunities skill, which logs a meeting with one save.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Logging a meeting changes the client's opportunity and adds the meeting's Task in one call, so one review covers both, and a part Salesforce refuses saves nothing | api | 1-3 | 2 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins on | The layer starts tools-service with `OPS_PLUGINS=true` |
| The Salesforce plugin | ops-ai-plugins with `save_records` (0.3.0), beside ops-ai or named by `OPS_SALESFORCE_PLUGIN` |
| A fake Salesforce | `docs/usecases/lib/fake_salesforce.py`, Dana Whitfield's advisor org: the Okafor Family Trust, Grace Okafor, the open Education savings opportunity at $50,000 in Needs Analysis; its composite resource applies all or none |
| People | Sam Adeyemi (platform admin), Priya Shah (team_ops admin); password `northfield-demo` |

## Steps

| # | Do | Expect |
|---|---|---|
| 1 | Call `salesforce_save_records` with the opportunity's new stage and amount, then a Task on it | One composite request; the opportunity is in Proposal at $75,000 and one new Task names it |
| 2 | Call it again with a new stage and a Task whose date Salesforce cannot read | Refused; the opportunity keeps Proposal and $75,000, and no Task is made |
| 3 | Read the refusal | It says nothing was saved and names `ActivityDate`, never `PROCESSING_HALTED` |

Run: `make usecase-test UC=uc-668 LAYER=api`.
