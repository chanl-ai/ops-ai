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
caller (a second skill, run as a step, whose sentence check a judge model decides) and place the freeze (a write that waits for a person, checked by a rule on
what the bank answered). It assumes a tool module
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
| S7 | A builder adds Tone and a section of his own to a brief, and the prompt shows them in order with Never last | api, sdk, cli, ui | 24, 25, 26, 27, 28 | 24 |

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
| 4 | James saves and publishes a one-step skill and a three-step skill that runs it, then adds the three-step skill to the agent. He also saves a write step with no rule check, and a step that only names a tool in its sentence | The read's and the write's checks are marked `rule`; the insert adds the skill, the skill it runs and the write tool it names. The write step with no rule is refused, 400 `write_needs_rule`; the step that only names a tool runs none and the publish check blocks on it (`bad_step`). A skill saved as text whose `if not result.balance > 0:` / `stop "..."` lines guard the read (api) stops a run on an account that owes money and holds the write after it (`skillRun.holds`) |
| 5 | James asks to publish and Maya approves | The check is clear, the agent is live and `uses` counts 2 tools and 2 skills |
| 6 | James chats: asks for the freeze before any skill is started, then starts the skill, makes the read, asks an unrelated question, gives the date of birth so the judge passes the confirm step, asks for the freeze | The freeze asked for first is refused: no person is asked and the bank receives nothing. The replies' `skillRun` then reads step 1, step 2 inside the second skill, the same again, step 3, and step 3 while the write waits for a person; the bank has received no freeze. A rejected freeze ends the skill as failed with `why: denied`. A second skill, with each tool picked inside its step's sentence, ends as blocked on an account that owes money, the record giving the rule, the ending's meaning, step 1 and `inReply: true`; the next reply can start it again, and it goes on to step 2 on an account with money; the write its test chat waits on is listed in Human Tasks. On the dev stack, a step that asks another agent is refused without a rule check, the hand-off is refused before its skill starts, and it runs as the step |
| 7 | The SDK creates and publishes the two skills, then saves a write step with no rule check | The stored steps run a tool, a skill and a tool, the read's and the write's checks are rules, and the save without one is refused, 400 `write_needs_rule` |
| 8 | The SDK applies an agent definition with a brief, asks the publish check, adds the tool and the skill, publishes | One problem before, none after, and the agent is live |
| 9 | `opsai skills apply` and `publish`, `opsai agents apply`, `publish-check`, `add-reference`, `publish` | The same result from files, with the publish waiting for review or live; a file whose write step has no rule check is refused |
| 10 | James opens the three-step skill in the console, which draws its notes and steps as one plain text (a text editor, not a list of step cards), types `@` in the middle of step 2 and picks a tool. A skill written as text with an `if` line is opened too | The page draws the notes and three steps as one text; the tool is drawn once and saved as the step's `use`. Each `if` line ends with a mark: `checked` when the tool above returns what it tests, `agent decides` when it is the agent's own words. A reviewer opens the same skill with the text read-only. With text unsaved and a newer version saved by someone else, his save is refused; Reload shows their text and name, keeps his text as a read-only copy he can open, and nothing saves over their text unless he copies from it or uses it; the next save holds their text and what he copied in |
| 12 | On the agent page James types `@` in the brief | The menu lists a tool the agent lacks and says what picking it adds |
| 13 | James picks the tool | The tool is added to the agent and the brief saves |
| 17 | James opens the test chat, then a chat whose reply ended a skill on a reviewer's rejection | The panel shows the skill and the step it is on; the chat view shows, once under that reply, that the skill stopped at step 3 because a reviewer rejected the action |
| 20 | Two sessions read the same agent draft and both save (api); Priya saves a new Goal in the brief and switches parallel reads off while James has the agent page open, and he changes the brief's Purpose and Thinking (ui) | The second save is refused, 409 `stale_base`, naming who saved and when, and a save that names no copy is refused, 400; the page says who saved and keeps his change, and Reload saves his Purpose and Thinking with her Goal and her parallel reads |
| 21 | Two sessions save the same skill draft (api); James saves the agent from elsewhere, then changes a field on the page (ui) | The second skill save is refused under the same version number; the page reads the agent again and saves with no message |
| 22 | Two sessions send the skill as text (`source`, the text editor's save) from the same copy (api) | The second save is refused, 409 `stale_base` with the shared error shape naming who saved; the stored text is the first session's |
| 23 | James and Maya reach the workflows list and canvas, the skill page (James types a mention, then resizes) and Human Tasks by the sidebar's links at 1440 and 390; with skill publishes set to always need a review, Maya opens James's publish from Human Tasks (ui) | No console errors on any of those pages; the open task is the `review-sheet` with its `review-approve` button |
| 24 | James saves a brief with a custom section and Tone, in that order, and opens View prompt (the prompt route); he then names a custom section `never` | The reply's `brief.sections` holds both with `kind`, `name` (Tone's fixed title filled in) and `text`; the prompt's headings read Who you are, Tone, How to answer, his section, Hand off when, Never, ending with the never rule. The second save is refused, 422 `validation_failed`, the message naming `brief.sections`, and the stored sections stay |
| 25 | James saves a brief with no `sections`, as every brief before them | `brief.sections` is `[]` and the prompt's headings are the ones it had: Who you are, How to answer, Hand off when, Never |
| 26 | The SDK applies an agent definition whose brief has `sections`, reads it back and reads the prompt | The same two sections and the same heading order |
| 27 | `opsai agents apply` on a file whose brief has `sections`, then `export` | The export prints `brief.sections` and `instructions` with the headings in order |
| 28 | James opens an agent whose brief has no sections, picks Tone from Add section and then Add custom section (the menu's last item), names it and writes both; he opens View prompt; Maya opens the same agent (ui, 1440 and 390) | The agent opens with no added section and View prompt reads as the service writes it. Both sections save and are drawn, each with a Remove control; View prompt shows Tone before How to answer, his section after it and Never last; at 390 nothing scrolls sideways. Maya reads both sections and sees no Add section and no Remove |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-757-api.py` | passes |
| sdk | `agents-service/scripts/test-uc-757-sdk.py` | passes |
| cli | `agents-service/scripts/test-uc-757-cli.py` | passes |
| ui | `agents-service/scripts/test-uc-757-ui.mjs` | see the registry row |

## Non-vacuous check

Step 6. The third reply calls no tool, and the fourth still finds the skill inside step 2. Without the record carried
between replies every reply starts with no skill running: with `carried_run` left out of the turn, step 6 failed with
the trail `(1, False), (None, None), (None, None), (None, False), (None, False)`, 13 of 14 checks passed. Step 3 is the
second: it pairs the refused publish with the publish that goes through once the tool is added.

Step 6 also runs a skill whose steps hold the tool picked inside each sentence, as the console saves them, on the
agent page's test chat. The account with money going on to step 2 is the paired check, so the skill does not end as
blocked for any other reason. The freeze asked for before any skill is started is paired with the same call reaching a
reviewer once the skill is on step 3.

Step 24 is the check for the added sections: they are saved with the custom section first and the prompt still reads
Tone before How to answer and the custom section after it, so a prompt written in saved order fails it. Step 25 is its
pair: the same brief without sections gains no heading. In step 28 the builder seeing Add section and two Remove
controls is paired with the person who cannot edit seeing none on the same agent.
