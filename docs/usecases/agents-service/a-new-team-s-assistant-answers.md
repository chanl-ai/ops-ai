# A new team's assistant answers from its knowledge and files

Status: passing. Id: `uc-619`. Service: `agents-service`. Layers: api.

A team made after install gets its built-in apps (Knowledge, Files, Document types, Mailboxes) and its Ops Assistant
from the `team.created` event, with no dev seed. Its assistant then answers from the team's knowledge and files.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A workspace admin makes a team, and before anyone opens it the team has its built-in apps and its Ops Assistant | api | 1, 2 | 2 |
| S2 | A person of the team asks the assistant a question, and it answers from the team's knowledge base | api | 3, 4 | 4 |
| S3 | The assistant reads a file the team uploaded | api | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Its own platform, tools, agents (scripted model), kb, files and documents services on a fresh database | the script starts them |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru (workspace admin) makes the Claims desk team, with Priya as its admin | 201 |
| 2 | Read the team's Apps cards and default chat agent, without opening the team first | four built-in cards; the default is `ag_ops_<team>` |
| 3 | A person of the team makes a knowledge base, uploads a chargeback rule and syncs it; uploads a handover note to Files | the source indexes the rule |
| 4 | Start a chat with no agent named; ask the assistant to call `search_knowledge` | the thread's agent is `ag_ops_<team>`; the call returns the rule through the gateway |
| 5 | Ask it to call `read_file` on the handover note | the call returns the note's text |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-619-api.py` | passing |

## Non-vacuous check

Step 2 fails when platform-service's relay cannot reach tools and agents (both URLs pointed at a closed port): no
built-in cards and no default agent, `([], '')`. Step 4 failed when tools-service started without its knowledge
search wired in ("This tools-service searches no knowledge").
