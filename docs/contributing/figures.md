# Figures

Status: current. Every figure the docs site can draw, each shown with the markdown that makes it and when to pick it
over the others. The rules every figure follows are on the [figure guide](figure-guide.md).

Each figure is a plain markdown list (or two code blocks) under a one-line marker, so the page still reads on GitHub.
The marker's `caption` is required: it is the figure's accessible name. A typo in a marker's kind fails the build.

| The text explains | Figure |
|---|---|
| A flow a person sees, step by step | [Journey](#journey) |
| One screen whose parts protect the reader | [Annotated screen](#annotated-screen) |
| One small panel, beside the paragraph about it | [Widget](#widget) |
| What a whole page of the console looks like | [Preview](#preview) |
| A system's layers, from where work arrives to where calls leave | [Layers](#layers) |
| How something is today and how it is with the feature | [Before and after](#before-and-after) |
| Who talks to whom, in order (an API call, a sign-in) | [Sequence](#sequence) |
| The states something passes through and what moves it on | [State](#state) |
| A choice the reader makes, with two or three answers | [Decision](#decision) |
| Two or three options, one of them recommended | [Compare](#compare) |
| What happens over minutes, hours or days | [Timeline](#timeline) |
| A command or request and what comes back | [Request and response](#request-and-response) |

## Journey

Use it for a flow told as the screens a person sees, three to six steps. Use a sequence instead when the steps are
calls between systems with no screen, and steps when the reader does the work.

<!-- site: journey source caption="A repair-shop invoice from arrival to payment, as the accounts team sees it" -->
1. **Team mailbox · An invoice arrives**: The message lands in the team's mailbox and is read for its fields.
   - **From**: billing@eastside-auto.example
   - **Subject**: Invoice 4471, claim CLM-2291
2. **Workflow · The claim is matched**: The workflow finds the open claim the invoice belongs to.
   - **Claim**: CLM-2291, approved for repair
   - **Limit**: $1,500.00
3. **Human task · A person approves payment**: The payment is a write, so it waits for someone on the team.
   - **Amount**: $1,480.00
   - **Actions**: Approve, Reject
4. **Case · The record holds every step**: The case keeps the invoice, the match and the decision together.
   - **Status**: Paid

## Annotated screen

Use it for one screen whose parts each protect or inform the reader, with at most five numbered notes. Use a widget
instead when the panel is small and the notes are few, and a preview when the reader needs the whole page.

<!-- site: annotated source caption="A refund waiting for approval, each protection numbered where it applies" -->
- **Human task · Approve a refund**: Requested by the returns agent for order 88213
- **Amount**: $64.00
  - The exact amount the tool will send. Changing it after approval voids the approval.
- **Requested by**: Returns agent
- **Waiting**: 3 hours
  - Past the team's review deadline the task shows as overdue.
- **Actions**: Approve, Reject
  - Only someone with the approver role sees these buttons.

## Widget

Use it for one small panel (two to four rows, up to three notes) that sits beside the paragraph about it. On a wide
screen it floats right of the next paragraph; on a phone it sits above it. Use an annotated screen when the notes are
the point of the figure.

<!-- site: widget source caption="An agent's knowledge answer, with the source it quoted" -->
- **Agent · Payoff question**: Answered from the lending handbook
- **Answer**: A payoff statement is valid for 10 days.
- **Source**: Lending handbook, section 4.2
  - Every answer names the page it came from, so a reviewer can check it.

The paragraph after a widget wraps beside it on a wide page. Keep the paragraph about the panel, so the two read
together, and keep the widget out of a section that ends before the paragraph wraps past it.

## Preview

Use it for "what you will see" moments: a whole console page, with the real sidebar, the page's list and one open
panel. Below 600px of figure width only the open panel shows, at its natural size, because the whole screen would be
too small to read. Use an annotated screen when only the panel matters. Previews have no tabs: a drawn tab would look
clickable and do nothing.

<!-- site: preview source caption="Human tasks in the console: the queue on the left, the open task on the right" -->
- **Human Tasks · Waiting for you**: Three decisions are waiting for your team
- **Columns**: Task, Team, Waiting, Status
- **Row**: Settle claim CLM-2291, Claims, 2 hours, Waiting
  - The open task is highlighted; its details are on the right.
- **Row**: Refund order 88213, Returns, 3 hours, Overdue
- **Row**: Raise a credit limit, Lending, 20 minutes, Waiting
- **Panel · Settle claim CLM-2291**: Payment to a repair shop
  - **Payee**: Eastside Auto Body
  - **Amount**: $1,480.00
    - The amount is fixed when the task is created; approving sends exactly this.
  - **Actions**: Approve, Reject

The sidebar is the console's own navigation, so a preview can only select a page the console has. The first row is
the one shown open.

## Layers

Use it for a system at a glance: where work comes from, the platform's layers inside one frame, and the outside
systems every call leaves to. Use the architecture diagram instead when the reader needs the boxes and their links.

<!-- site: layers source frame="Ops AI, on your infrastructure" caption="A support request from the help desk to the ticket system and back" -->
- **Where work comes from**: People and systems that start work
  - **Help desk chat**: A customer asks about an outage
  - **Status page**: Posts an incident
- **Agents and workflows**: Do the work
  - **Support agent**: Answers from the runbook
- **Gateways**: Every call leaves through one
  - **Data gateway**: Calls the ticket system
  - **AI gateway**: Calls your model
- **Your systems**: Outside Ops AI
  - **Ticket system**: Holds the incident

## Before and after

Use it for one change shown as two sides: how it is today and how it is with the feature. Match the points in order so
the sides read across. Use compare instead when there are two or three real options to choose between.

<!-- site: before-after source caption="Answering a coverage question, by hand and with a team agent" -->
- **Today**: An agent searches three policy binders while the caller waits.
  - The answer depends on who picked up
  - Nobody can say later which page it came from
- **With Ops AI**: The team's agent answers from the policy handbook in seconds.
  - Every person gets the same answer
  - The answer names the page it quotes

## Sequence

Use it for who talks to whom, in order: an API call through the gateways, a sign-in with an identity provider. At
most five participants and twelve messages. On a phone each message is a row naming both ends. Use a journey instead
when each step is a screen a person sees.

<!-- site: sequence source caption="Signing in with your identity provider: the console never sees the password" -->
1. **Person → Console**: Opens the console
2. **Console → Identity provider**: Sends the person to sign in
3. **Person → Identity provider**: Signs in with their work account
4. **Identity provider → Platform**: Returns a signed answer
   - The platform checks the signature and the email domain.
5. **Platform → Console**: Starts a session of up to 8 hours

## State

Use it for a lifecycle: the states something passes through, what moves it on, and how it can end. Each nested bullet
is a transition: the next state in bold, then what triggers it. Use a decision instead when the reader chooses, and a
timeline when time is what moves it on.

<!-- site: state source caption="A workflow version from draft to published, and the ways a publish can stop" -->
- **Draft**: Saved and checked, not running anywhere
  - **In review**: Someone requests the publish
- **In review**: A second person reads the change
  - **Published**: The reviewer approves
  - **Rejected**: The reviewer sends it back
- **Published**: New runs start on this version
- **Rejected**: Stays a draft until someone fixes it

## Decision

Use it for a short choice: a question with two or three answers, each ending in an outcome or one more question, at
most three questions deep. Use a table instead for more answers or more depth.

<!-- site: decision source caption="Whether a tool call waits for a person" -->
- **Does the tool change anything?**
  - **No, it only reads**: It runs at once and is logged.
  - **Yes, it writes**: The team's policy for that tool decides.
    - **Does the policy ask for a reviewer?**
      - **Yes**: The run pauses until a person approves the exact input.
      - **No**: It runs and is logged with who asked.

## Compare

Use it for two or three options side by side with the recommended one marked by `pick`. Give each option the same
rows in the same order, at most five. Use a table instead for more options or rows.

<!-- site: compare source pick="One machine" caption="Two ways to run Ops AI, and which to start with" -->
- **One machine**: Docker Compose on one Linux host
  - **Good for**: A pilot or a single team
  - **Needs**: 4 vCPUs, 8 GB memory, PostgreSQL
  - **Upgrades**: One script
- **Kubernetes**: The services on your cluster
  - **Good for**: Many teams, your own scaling rules
  - **Needs**: A cluster, PostgreSQL, a volume each for files and knowledge
  - **Upgrades**: A new chart version

## Timeline

Use it for what happens over minutes, hours or days: three to six moments. Use a state figure instead when events, not
time, move it on.

<!-- site: timeline source caption="How long an approval stays good" -->
- **0 minutes**: A person approves the exact input
- **15 minutes**: The approval token expires
  - A run that resumes later renews it from the recorded decision.
- **8 hours**: A review not yet decided shows as overdue
- **24 hours**: A late resume can no longer renew the token

## Request and response

Use it for a command or an API request and what comes back, drawn as two product panels. The request block takes a
`title`, the response a `status`. Keep each to about twelve lines. Use a code block instead for a whole program.

<!-- site: exchange source caption="Starting a run of the dispute workflow from the command line" -->
```bash title="Start a run"
opsai workflows run card_dispute_intake --input dispute.json --wait
```

```json status="201 Created"
{
  "runId": "run_7f2c",
  "status": "waiting",
  "waitingOn": "human_task",
  "taskId": "task_19ab"
}
```

## Not in the library

A row of three or four headline numbers was considered and left out. The numbers on the docs pages are limits and
sizes, and each needs its condition beside it, which a table already gives.
