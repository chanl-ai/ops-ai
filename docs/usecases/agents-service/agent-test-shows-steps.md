# Agent test replies show what the agent did

Status: current. Id: `uc-133`. Service: `agents-service` and `console`. Layers: ui.

A builder testing an agent saw one line of text back and could not tell whether it searched anything, called a tool
or would have paused. Each test reply now carries a steps block: the knowledge it searched and cited, the tools it
called and how each went, and where it would pause for a review, each saying so when there was nothing. Since c-285 the
test is a real chat in the agent page's right panel, and the steps are its Why tab; each case starts a new test, since a
thread paused on an approval takes no new message.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents, platform-service and console (ISOLATED=1 adds 1000) |

The agents service runs on the scripted model with the seeded Wire Fraud Sentinel (`ag_fraud`): it holds
`lookup_account` (read) and `place_wire_hold` (a write that pauses), and searches kb_people and kb_eng.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Wire Fraud Sentinel, Test, sends "Place a 24-hour hold on wire W-88213" | Why says place_wire_hold was stopped for a review and names whom the review waits on |
| 2 | New test; he sends "What is the daily wire limit?" | Why cites passages with their knowledge base |
| 3 | New test; he sends "Hello" | Why says it called no tools, names the tools it holds, and that place_wire_hold pauses when called |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-133-ui.mjs` | passing |
