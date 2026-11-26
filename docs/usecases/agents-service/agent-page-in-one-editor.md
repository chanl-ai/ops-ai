# A builder edits an agent's brief and what it uses on one page; a viewer and a member read it

Status: current. Id: `uc-948`. Service: `agents-service`. Layers: api, sdk, cli, ui.

Short title: A builder edits an agent's brief and what it uses on one page

## Story

As a builder, I want an agent's brief, its tools, knowledge and skills, its channels and its versions on one page that
reads the same for everyone, so that I can change what it does without hunting between boxes, and a viewer or a member
can read what they may and change none of it.

## People

| Person | Role | Does what |
|---|---|---|
| James Richardson | builder | Writes the brief, saves, sends a publish for review, takes it back |
| Ravi Menon | viewer | Opens the page and the waiting version and changes nothing |
| Lena Brandt | member who only chats | Is told the page is not hers |
| Maya Okafor | approver | Approves the publish (ui setup) |

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A brief with seven fields saves, makes a prompt with Never last, and a waiting version is never edited in place | api | 1-4 | 3 |
| S2 | A developer does the same through the Python SDK | sdk | 5, 6 | 6 |
| S3 | A developer does the same from a file with `opsai` | cli | 7, 8 | 8 |
| S4 | The page reads as designed for a builder, a viewer and a member at 1440 and 390 | ui | 9-22 | 20 |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James saves a brief with purpose, goal, how to answer, hand off, examples, never and success checks | It reads back with every field the same |
| 2 | He reads the prompt the brief makes | The bands come in order and Never is last |
| 3 | He sends a publish, saves a change while it waits, takes the request back and sends it again | The waiting version names its review and is not rewritten; the save opens the next version; both the withdraw and the second request succeed |
| 4 | He mentions a workflow the team lacks | The publish check says it cannot be requested, in the one blocker shape |
| 5 | The SDK applies an agent with a seven-field brief and reads it back | The same fields |
| 6 | The SDK asks the publish check for an agent that mentions a workflow the team lacks | `canRequest` is false and `blockers` holds one entry with a code and a message |
| 7 | `opsai agents apply` then `export` | The seven fields come back equal |
| 8 | `opsai agents publish-check` for the same kind of agent | The same blocker shape |
| 9 | James and Ravi open an agent's page | The brief reads as Job, How to answer, Hand off when, Examples and Never, with no success checks in it |
| 10 | The same page | No identity box |
| 11 | Each tab is pressed; Compare is opened | Each tab has its own address; Compare is its own page with no test panel |
| 12 | James opens the channels of a published agent | One list of seven places (Chat, API and SDK, MCP, Embed on a page, Email, Slack, Teams), each On or Not set up |
| 13 | James and Ravi press View prompt | The prompt is read-only and Never comes last |
| 14 | The brief's footer | It holds the uses link and View prompt |
| 15 | James renames the agent and presses Cmd+S | The header says Unsaved, then Saved, in the four words |
| 16 | The header | Save state, Save, Test, Publish, menu in that order; no label over two words |
| 17 | The page | Tools, Knowledge and Skills are sections on it |
| 18 | James opens a skill | It opens on its instructions with an Insert menu and one Used by list |
| 19 | Every page above at 390 and 1440 | No page scrolls sideways and none logs an error |
| 20 | James opens an agent whose publish waits and presses Withdraw | The request goes through, the version is a draft again and the page shows no open review, and Send again is offered |
| 21 | Ravi opens the same agent | He sees it is in review and no Withdraw |
| 22 | Ravi opens a draft agent; Lena opens it too | Ravi sees the view only note with no Save and no Test; Lena is told she has no access |

## Scripts

| Layer | Script |
|---|---|
| api | `scripts/test-uc-948-api.py` |
| sdk | `scripts/test-uc-948-sdk.py` |
| cli | `scripts/test-uc-948-cli.py` |
| ui | `scripts/test-uc-948-ui.mjs` |

## Non-vacuous check

Step 3 failed on the version list that did not name the waiting review (`reviewId` was null). Step 20 failed with the
console posting the withdraw to `/publish-requests/...` without `/v1` (404): the version stayed `in_review` and the page
kept its open review. Both pass with the list naming the review and the withdraw sent to `/v1/publish-requests/...`.
The other ui steps lock in what was built.
