# Schedule a workflow or an agent

Status: current. Written for the console; the same schedule can be set from a terminal or a script ([Workflows](workflows.md#run-a-workflow-on-a-schedule)).

A schedule starts a workflow by itself: a held-wires check every 15 minutes, a morning report at 07:30 on weekdays. You
set it on the workflow's Schedule trigger, and it takes effect when you save, with no publish.

## Set a schedule on a workflow

1. Open the workflow and open its Schedule trigger. The sheet's Schedule section (marked Not part of a version) shows the
   saved schedule, or an empty form for a new one.
2. Set Every (a number and minutes, hours or days) and, if you want, Starting at.
3. Untick the days it should not run, or set Between two times to narrow it. Left alone it runs every day, day and night.
4. Pick the Time zone. The search opens on your own zone.
5. Read Next runs. It lists the next three times in the zone you chose, and the schedule in words, for example
   "Every 15 minutes from 07:00, Europe/London".
6. Press Save schedule. It applies at once to the live version of the workflow. The panel says who changed it and when.

A value the server refuses is shown beside its field, and what you typed stays: a gap shorter than the install's shortest
interval ("At least 5 minutes on this install."), no day chosen, hours that end before they start, a time zone it does
not know. A scheduled run carries only the time it was due, so the trigger's input may not require anything else.

## What the panel tells you

| You see | It means |
|---|---|
| Saved. Not running yet | The workflow has no live version. The schedule starts at its next time once one is published. |
| Paused: no scheduled runs | The workflow is paused. Pause in the header stops the whole workflow, not only the schedule. Resume waits for the next time on the schedule. |
| Last scheduled run | When the last time came and what happened, in one of six words: ran, ran late, skipped (the run before it was still going), refused (the run could not start), missed (the clock was down) or seen (the clock noted the schedule at that time and started nothing). A reason follows the word when there is one, and a run that started links to it with Open the run. |
| A saved schedule is not running (above the canvas) | A newer version removed the Schedule trigger, so there is no step to run. The notice says why and offers Clear schedule. |

Clear schedule asks first. Scheduled runs stop; runs already started carry on, and the workflow is not paused.

A schedule saved from a terminal or a script shows on the trigger when you open it. The trigger's Key sits under
Advanced once a schedule is set.

## Run an agent on a schedule

An agent runs on a schedule through a workflow that has the agent as its step, so a script does the same by making that
workflow.

1. Open the agent, then its Channels tab. Under Where it's live, choose Schedule (Run on a schedule).
2. Name the workflow, say what to ask the agent, and set the schedule as above.
3. Choose Create workflow. The editor opens on the new workflow.
4. Publish the workflow. Once it is published, the agent's list shows it with the schedule in words and its next run.

The list shows only the workflows of teams you may view. An agent that is not live anywhere reads "Not live anywhere
yet", with the three ways to put it to work.

## Who can do what

Anyone who can view the workflow reads its schedule, next runs and last run. Saving or clearing a schedule needs the right to edit the workflow and the right to add deployments in its team (Builders
and Admins have both); resuming a paused workflow needs only the right to edit it. A Member sees the schedule and no
Save, Clear schedule or Resume.
