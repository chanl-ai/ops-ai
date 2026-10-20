# An agent remembers each person, and they manage what it keeps

Status: current. Id: `uc-134`. Service: `agents-service`. Layers: api.

A person used to repeat their timezone, account and role in every new chat. With memory on (the default), what they
say about themselves carries into their next chat with that agent, and only theirs; they can list, correct, export and
forget it, and a forget is recorded.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790 (ISOLATED=1 adds 1000) |

The agents service runs on the scripted model, which answers the memory extraction: "My <key> is <value>" is a fact.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Maya tells Branch Concierge "My timezone is Eastern." | Her memories list timezone: Eastern |
| 2 | In a new chat she asks it to search its memory for her timezone | The search_memory call returns Eastern |
| 3 | She corrects it to Pacific | Her list shows Pacific only |
| 4 | James lists his memories | None |
| 5 | Maya forgets it, then the agent searches again | Her list is empty, the search finds nothing, and her export records the correction and the forget |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-134-api.py` | passing |
