# Chat and channels

Status: current. Rows marked planned are designed and not built.

Staff should be able to ask for something in plain words, and other systems should reach the same agents without a
person in between. A chat is a conversation with an agent or with the team's Ops Assistant, which looks things up in
your team's apps and replies with what it read. A channel is where that conversation, or a workflow run, comes in.

## Try it

Open **Chat** in the console and ask a question, or from the command line:

```bash
opsai chat say -m "Which customers have a card dispute open?"
opsai chat say --agent "Branch policy" --test -m "What is the daily cash limit at a branch?"
opsai chat say --thread <thread-id> -m "And who owns the first one?"
```

The reply streams with its sources. The command prints a link to the same conversation in the console. The assistant
acts as you, so it reaches only what your own sign-in allows.

## Channels

| Channel | What comes in | Status |
|---|---|---|
| The console's chat | People chatting with the team's agents and the Ops Assistant | built |
| A chat on your own pages | The same chat in an iframe on an intranet page ([Chat on your own pages](../console/embedding-the-chat.md)) | built; the installer does not run it yet |
| A team mailbox | Emails that start a workflow, read once each, over IMAP, Gmail or Microsoft 365; replies go from the mailbox's address | built |
| The HTTP API | Other systems starting a run or an agent with a team API key | built |
| MCP | AI assistants calling the team's tools | partial: read tools, as test runs |
| A due time | A run that starts when a date passes | built. A recurring schedule is planned |
| A webhook from another system | A signed incoming request that starts a run | planned |

## A checklist for longer asks

An ask that needs several lookups, more than one App, or a change shows a short checklist above the answer. The assistant
ticks each step off as it finishes it.

## When a sign-in is needed

If a step needs an App you have not connected, the assistant stops at that step and shows a **Connect** card. Press it,
sign in, and the chat carries on at the same step. Nothing is retyped.

## Think harder

A reply that took a plan or several lookups offers **Think harder**. One press answers the same question again on the
deeper model. Writing "think harder" in a message, alone or with the question, does the same.

## Saving to an app

Before it changes anything in an App, the assistant reads the change back to you. It writes only after you say **Save**.
Until then nothing in the App has changed.

## Follow-ups

- **Reused reads.** A chat reuses what it already read from an App for 5 minutes, so a follow-up answers faster. The reply
  says when it used an earlier read. A save to that App clears the reused reads, so the next look reads the App again.
- **Suggestion chips.** Under a reply, short chips offer likely next questions. Press one to ask it.
- **Memories.** The assistant suggests what to remember and asks first. It keeps nothing silently.

## Attached files

A file you attach in chat is read once, and the assistant gets its text whole, up to about 24,000 characters for the
turn. This covers scanned pages, half-scanned pages, images of text and filled forms (the typed values in a form's
fields are read too). Scans are read by OCR, so a long scan can take a moment before the assistant answers. If a file is
longer than the limit, or could not be read, the reply says so in words.

## Replies without a matching source

When no knowledge passage matched your question, the reply keeps its lists and paragraphs, with a note under it:
"No knowledge passage matched this question." The reply is often still a full answer, such as a question back or a
plan.

The assistant states facts about your organisation (policies, processes, timelines, fees, products, teams, customers)
only when your knowledge or a tool result in the chat gives them. When neither does, it says it does not have that
information and what it can do instead. When a reply that uses knowledge lacks source numbers, the check adds the
numbers. It does not replace a correct answer with "nothing found".

## Which app and which account

- A chat uses the Apps your team turned on. The **Connectors** button in the chat box lets you leave an App out of that
  chat, before or during the chat.
- The button shows the icons of the Apps in use (up to four, then a count). The list stays open while you check and
  uncheck Apps, and each row shows the App's icon. An App that needs your sign-in has a **Connect** button in its row.
- With two accounts of the same App connected and no default, the assistant asks which one to use. Your pick becomes the
  default for calls that name no account.
- An App your team has off shows a card with **Ask an admin**.

Your sign-ins are managed on **Apps › Mine** ([Apps](apps.md#your-own-sign-ins)).

## Next

<!-- site: cards -->
- **[Agents](agents.md)**: build the agent people chat with.
- **[Knowledge](knowledge.md)**: the sources a reply cites.
- **[Human tasks and approvals](human-tasks.md)**: what happens when a chat asks to change something.
