# A builder writes a skill with steps and an agent brief, and a chat follows the steps

Status: current. Id: `uc-757`. Service: `agents-service`. Layers: api, sdk, cli, ui.

Short title: A builder writes a skill with steps and an agent brief, and a chat follows the steps

## Story

As a builder, I want to write an agent as a short brief and its procedures as skills with numbered steps, so that the
agent follows each procedure one step at a time and a chat goes on from the step the last reply reached.

## People

| Person | Role | Does what |
|---|---|---|
| James Richardson | builder | Writes the skills and the brief, adds what the brief mentions, asks to publish, chats |
| Maya Okafor | approver | Approves the agent's publish, since a brief's never rules are reviewed by a second person |
| A member with read-only access | viewer | Opens the agent and skill pages and can change nothing (ui) |

## In this example

In this example we will freeze an account in three steps: read the account (a rule checks the result), confirm the
caller (a second skill, run as a step) and place the freeze (a write that waits for a person). It assumes a tool module
with a read and a write on a mock bank, published for the team, and platform sign-in with the seeded people.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder saves something else on an agent written before the brief, and its prompt stays as it was | api | 1 | 1 |
| S2 | A builder writes a brief, and the agent cannot publish until what the brief mentions is added | api | 2, 3, 4, 5 | 3 |
| S3 | A person chats, and each reply goes on from the step the last one reached | api | 6 | 6 |
| S4 | A developer does the same through the Python SDK | sdk | 7, 8 | 8 |
| S5 | A developer does the same from files through `opsai` | cli | 9 | 9 |
| S6 | A builder types `@` on the agent page, adds a tool, and the test chat shows the step | ui | 10, 12, 13, 17 | 13 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| A read tool and a write tool that needs approval | The scripts publish a tool module on a mock bank (`lib/main_chains.py`, `publish_bank_module`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James grants a tool to an agent that has no brief | The reply has `brief: null`, `promptMode: null` and the same `instructions` |
| 2 | James saves a brief on a second agent, renames it, then tries to save `instructions` alone | `promptMode` is `brief` and the instructions start with `# Who you are` and the agent's name; the rename rewrites them; the last save is refused, 422 `brief_owns_prompt` |
| 3 | The brief mentions a tool the agent lacks; James asks what blocks the publish, tries to publish, then adds the tool twice | The check lists `missing_reference` for that tool at `brief.howToAnswer`; the publish is refused, 422 `cannot_publish`; the first insert adds the tool and the second adds nothing and saves no version |
| 4 | James saves and publishes a one-step skill and a three-step skill that runs it, then adds the three-step skill to the agent | The first step's check is marked `rule`; the insert adds the skill, the skill it runs and the write tool it names |
| 5 | James asks to publish and Maya approves | The check is clear, the agent is live and `uses` counts 2 tools and 2 skills |
| 6 | James chats: starts the skill, makes the read, asks an unrelated question, confirms the caller, asks for the freeze | The replies' `skillRun` reads step 1, step 2 inside the second skill, the same again, step 3, and step 3 while the write waits for a person; the bank has received no freeze |
| 7 | The SDK creates and publishes the two skills | The stored steps run a tool, a skill and a tool, and the first check is a rule |
| 8 | The SDK applies an agent definition with a brief, asks the publish check, adds the tool and the skill, publishes | One problem before, none after, and the agent is live |
| 9 | `opsai skills apply` and `publish`, `opsai agents apply`, `publish-check`, `add-reference`, `publish` | The same result from files, with the publish waiting for review or live |
| 10 | James opens the three-step skill in the console | The page draws the three steps as one document |
| 12 | On the agent page James types `@` in the brief | The menu lists a tool the agent lacks and says what picking it adds |
| 13 | James picks the tool | The tool is added to the agent and the brief saves |
| 17 | James opens the test chat | The panel shows the skill and the step it is on |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-757-api.py` | passes |
| sdk | `agents-service/scripts/test-uc-757-sdk.py` | passes |
| cli | `agents-service/scripts/test-uc-757-cli.py` | passes |
| ui | `agents-service/scripts/test-uc-757-ui.mjs` | see the registry row |

## Non-vacuous check

Step 6. The third reply calls no tool, and the fourth still finds the skill inside step 2. Without the record carried
between replies every reply starts with no skill running, and the trail the check compares is empty. Step 3 is the
second: it pairs the refused publish with the publish that goes through once the tool is added.
