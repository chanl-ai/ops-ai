# Chat and channels

Status: current. Rows marked planned are designed and not built.

This page shows how your staff can ask for work in plain words in a chat, and how other systems can reach the same
agents without a person passing the request along.

## Why teams ask in chat, and why systems need a way in too

An operations team fields the same questions all day: which customers have a dispute open, what the branch cash limit
is, who owns a case. A claims handler asks which policy applies, and a lender's analyst asks where a loan stands.
Answering each one by hand means opening three systems and copying the result across. Another system that needs the
same answer has no way in unless a person relays it.

A chat is a conversation with one of your team's agents or with the team's Ops Assistant. The assistant looks things up
in your team's apps and replies with what it read. A channel is the route by which that conversation, or a workflow
run, arrives. Without channels, each new way of asking, from a mailbox to an API call, would need its own copy of the
agent and its own set of rules.

## From question to action

<!-- site: steps -->
1. **Ask.** Open **Chat** and type your question the way you would say it out loud.
2. **Check the answer and its sources.** The reply streams in, along with the passages and tool results it drew on.
3. **Approve any change.** When the answer needs a change in an app, the assistant reads the change back to you and
   makes it only after you choose **Save**.
4. **Connect other channels.** Point a mailbox, the HTTP API or a due date at the same agent, so work can start without
   anyone typing.

## Ask your first question

Open **Chat** in the console and ask a question. You can also ask from the command line:

```bash
opsai chat say -m "Which customers have a card dispute open?"
opsai chat say --agent "Branch policy" --test -m "What is the daily cash limit at a branch?"
opsai chat say --thread <thread-id> -m "And who owns the first one?"
```

The reply streams in with its sources, and the command prints a link to the same conversation in the console. Because
the assistant acts as you, it can reach only what your own sign-in allows.

## Where requests can come from

| Channel | What comes in | Status |
|---|---|---|
| The console's chat | People chatting with the team's agents and the Ops Assistant | built |
| A chat on your own pages | The same chat in an iframe on an intranet page ([Chat on your own pages](../console/embedding-the-chat.md)) | built; the installer does not run it yet |
| A team mailbox | Emails that start a workflow, read once each, over IMAP, Gmail or Microsoft 365; replies go from the mailbox's address | built |
| The HTTP API | Other systems starting a run or an agent with a team API key | built |
| MCP | AI assistants calling the team's tools | partial: read tools, as test runs |
| A due time | A run that starts when a date passes | built. A recurring schedule is planned |
| A webhook from another system | A signed incoming request that starts a run | planned |

## What you can do in a chat

### A checklist for longer requests

When a request needs several lookups, more than one app, or a change, the assistant shows a short checklist above the
answer. It ticks off each step as it finishes it.

### When you need to sign in to an app

If a step needs an app you have not connected yet, the assistant pauses at that step and shows a **Connect** card. Press
it and sign in, and the chat picks up again at the same step, so you do not need to retype anything.

### Think harder

When a reply needed a plan or several lookups, it offers **Think harder**. Pressing it answers the same question again
using the deeper model. You get the same result by writing "think harder" in a message, either on its own or alongside
your question.

### Approving a change to an app

Before the assistant changes anything in an app, it reads the change back to you, and it makes the change only after you
choose **Save**. Until you do, nothing in the app has changed.

### Follow-up questions

- For 5 minutes, a chat reuses what it has already read from an app with your own sign-in, so follow-up questions are
  answered faster. It does not reuse a read made on the team's account, because the team's account may see different
  records from the ones you can see. The reply tells you when it used an earlier read. Saving a change to that app
  clears the reused reads, so the next lookup reads the app afresh.
- Under a reply, short suggestion chips offer likely next questions. Press one to ask it.
- The assistant may suggest things to remember, but it asks you first. It does not store a memory without asking.

### Files you attach

When you attach a file in a chat, it is read once and the assistant receives its full text, up to about 24,000
characters for that turn. This works for scanned pages, partly scanned pages, images of text and filled-in forms,
including the typed values in a form's fields. Scans are read by OCR, so a long scan can take a moment before the
assistant answers. If a file is longer than the limit, or could not be read, the reply tells you so in plain words.

### When no source matches your question

If no knowledge passage matched your question, the reply still keeps its lists and paragraphs, and a note appears under
it: "No knowledge passage matched this question." The reply is often a complete answer anyway, such as a question back
to you or a plan.

The assistant states facts about your organisation (policies, processes, timelines, fees, products, teams, customers)
only when your knowledge or a tool result in the chat supports them. When neither does, it tells you it does not have
that information and suggests what it can do instead. If a reply that draws on knowledge is missing its source numbers,
a check adds them. That check does not replace a correct answer with "nothing found".

### Choosing apps and accounts

- A chat uses the apps your team has turned on. You can use the **Connectors** button in the chat box to leave an app
  out of a chat, either before you start or partway through.
- The button shows the icons of the apps in use, up to four and then a count. The list stays open while you tick and
  untick apps, and each row shows the app's icon. If an app needs your sign-in, its row has a **Connect** button.
- If you have two accounts for the same app connected and neither is the default, the assistant asks which one to use.
  The one you pick becomes the default for any call that does not name an account.
- If your team has turned an app off, you see a card with **Ask an admin**.

You manage your sign-ins on **Apps › Mine** ([Apps](apps.md#your-own-sign-ins)).

## When this is working

A member of staff asks a question in the console, and the reply streams in with its sources, drawing only on what that
person's own sign-in allows. Any change to an app waits until they choose **Save**. Meanwhile a mailbox, the HTTP API or
a due date can start the same agent without anyone typing.

## Without chat and channels

Without a chat, each question becomes a ticket for a person who then opens the same three systems. Without channels,
every system that needs an answer ends up with its own copy of the agent, and over time those copies drift apart.

## Next

<!-- site: cards -->
- **[Agents](agents.md)**: build the agent people chat with.
- **[Knowledge](knowledge.md)**: the sources a reply cites.
- **[Human tasks and approvals](human-tasks.md)**: what happens when a chat asks to change something.
