# Open a workflow step and pick a field

Status: current.

You can read what a workflow step does, fix what is wrong with it and fill its settings from earlier steps by name,
without writing a path or knowing a step type. This page follows one step from opening it to a saved setting.

## Open a step

1. Open **Build › Workflows** and pick a workflow. Its steps show on the canvas.
2. Click a step. A sheet opens beside the canvas and the canvas stays usable; clicking another step moves the sheet to it.
3. Use the arrows at the bottom of the sheet to walk to the previous or next step in the order they run.

A person who may only view workflows can open every step and read it. Their fields are greyed out and the sheet has no
Delete step button.

## Read the sheet from top to bottom

| Section | What it tells you |
|---|---|
| The title and the summary | The step's name, its kind (starts the workflow, works with data, asks a person and so on) and what it does in one sentence. **Learn more** opens a longer explanation |
| Fix before you publish | What is wrong with this step, in words, naming the step. **Fix** takes you to the setting to change |
| How it starts | On a trigger only: how a run begins, with the details a caller needs behind **Technical details** |
| What it receives | The fields of every earlier step, each with the value from your team's newest finished run. Before any run it says "No run yet" |
| Settings | The step's own settings. Required settings carry a mark, and each hint is one sentence |
| When it fails | How many times the step tries again, what happens if it still fails, and how long it may take |
| What it gives | The fields later steps can pick from this step |

Values that look like an email address or another personal detail are masked in What it receives.

## Pick a field from an earlier step

A setting that takes a value from the run, such as the output of an End step or the values of a Set fields step, has a **Use a field…** button. Free-text settings, such as a message body, do not.

1. Press **Use a field…**.
2. Type part of a name. The list groups the fields by **Run input** and by each earlier step, with the value from the
   last run beside each one.
3. Press Enter, or click a field. The setting shows a chip such as "Fields → Amount" and the workflow saves itself.
4. To change it, clear the chip and pick again, or type a value instead: text, a number or yes or no.

If nothing matches, the list says "Nothing matches." If the step a chip reads from was deleted, the chip says "Missing
step".

## Choose a step in a list

Some settings ask for another step, for example the review a payment waits for. The list shows steps by their names, and
offers only the kinds that fit: a review step lists the steps that make a change in an app, and an app step lists the
review steps.

## Fix a problem

Each problem names the step and says what to change. Press **Fix** and the sheet scrolls to the setting and puts the
cursor in it. A problem about how steps are connected, such as a step nothing follows, has no setting to change; connect
the step on the canvas.

## Related

- [Workflows](workflows.md) builds the same graph from the SDKs and the command line.
- [Human tasks and approvals](human-tasks.md) explains the review step.
