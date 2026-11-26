# Quickstart

Status: current. The command line is not on a public package index yet, so this page installs it from the clone.

**Run Ops AI on one machine and watch a workflow run in about ten minutes, with no model key and nothing to sign up for.**

## Seeing it run beats reading about it

You are deciding whether Ops AI can carry your team's work, and a slide deck cannot answer that. Many tools ask for
setup, a cloud account and a model key before anything runs, so the decision waits on a project nobody has approved yet. This page installs the real platform on one machine with a built-in test model, then runs a workflow
you can read in full and open step by step in the console.

## What waiting costs

Until someone runs it, the decision rests on someone else's demo. A pilot that starts without a first run on your own
machine tends to stall on the first unanswered question: what does a run look like, and what does it keep? Ten minutes
here answers both. To install for a team on a server, read [Install](install.md) instead; the steps are the same with
more questions answered.

## Before you start

| Tool | Used for |
|---|---|
| Docker 24 or newer, with Compose 2.22 or newer | Running Ops AI and its database |
| 4 GB of memory for containers and 15 GB of disk | The services, the database and the images |
| [uv](https://docs.astral.sh/uv/), or Python 3.11 or newer with pip | The `opsai` command line |

## Install and sign in

<!-- site: steps -->
1. **Install.** Clone the repository and run the installer. `--yes` takes the default answer to every question: the
   built-in database, the test model and a generated admin password.

   ```bash
   git clone https://github.com/chanl-ai/ops-ai.git && cd ops-ai
   ./install.sh --yes
   ```

   When it ends, it prints the address to open and how to sign in as the first admin, `admin@example.com`. The
   generated password is the `OPS_BOOTSTRAP_ADMIN_PASSWORD` line of `ops-ai.env` in the same folder; change it after
   the first sign-in, then delete that line. `./install.sh status` prints the address again.

2. **Open the console.** Open that address and sign in as the first admin.

3. **Install the command line and sign in.** From the clone:

   ```bash
   uv tool install ./sdk/python
   opsai login --base-url <the address> --email admin@example.com
   ```

   `opsai login` asks for the password and keeps the session in a profile, so later commands need no sign-in. See
   [Install the command line](install-cli.md) for pip, a company mirror or a machine with no network.

## Run your first workflow

The workflow below takes a support request, maps its fields onto one shape and ends. It has no model, tool or person in it.

<!-- site: steps -->
1. **Write the workflow.** Save this as `workflow.yaml`:

   ```yaml
   schemaVersion: 2
   id: normalize_support_request
   name: Normalize a support request
   nodes:
   - id: start
     type: ops.trigger.request
     typeVersion: 1
     name: Support request
     parameters:
       inputSchema:
         type: object
         required: [customerEmail, subject, message]
         properties:
           customerEmail: {type: string}
           subject: {type: string}
           message: {type: string}
   - id: map
     type: ops.data.set
     typeVersion: 1
     name: Canonical fields
     parameters:
       values:
         customer.email: $.input.customerEmail
         title: $.input.subject
         body: $.input.message
   - id: done
     type: ops.flow.end
     typeVersion: 1
     name: Accepted
     parameters:
       outcome: accepted
   connections:
   - {from: {node: start, port: payload}, to: {node: map, port: in}}
   - {from: {node: map, port: out}, to: {node: done, port: in}}
   ```

2. **Check it, save it and run it.**

   ```bash
   opsai workflows validate workflow.yaml
   opsai workflows apply workflow.yaml
   opsai workflows run normalize_support_request --wait \
     --input '{"customerEmail": "ada@example.test", "subject": "Card", "message": "Where is my refund?"}'
   ```

   The run ends `succeeded` with the outcome `accepted`. A request without `customerEmail` is refused at the start.

3. **See it in the console.** Open **Build › Workflows › Runs** and pick the run: each step shows its input and output.

4. **Call it from Python.** The same profile signs the client in.

   ```python
   from ops_ai import OpsAI

   ops = OpsAI()
   run = ops.workflows.run("normalize_support_request", wait=True,
       input={"customerEmail": "ada@example.test", "subject": "Card", "message": "Where is my refund?"})
   print(run["status"], run.get("outcome"))
   ```

A new run is a test run unless you ask for a live one with `--live`. Publishing a version, for live runs, is on
[Workflows](workflows.md).

## What success looks like

- `./install.sh status` prints an address, and you are signed in to the console at it as the first admin.
- `opsai workflows run` ends `succeeded` with the outcome `accepted`, and the same run is under **Build › Workflows ›
  Runs** with each step's input and output saved.
- The Python call prints the same status, so the command line and the code read one run.

## Use a real model or stop

| Task | Do |
|---|---|
| Answer with a real model | Run `./install.sh --model <OpenAI-compatible base URL ending in /v1> --model-name <model> --model-key-file <file>`; the key is stored in Ops AI's secrets, not in a file |
| Stop and keep the data | `./install.sh uninstall`, and answer no when it asks to delete the data |
| See what is running | `./install.sh status` |

## Next

<!-- site: cards -->
- **[Agents](agents.md)**: write an agent, publish it and chat with it.
- **[Workflows](workflows.md)**: publish, test from fixtures, and the step types.
- **[Build with Ops AI](build-with-ops-ai.md)**: the example folders in order, from one message to an agent that starts a workflow.
- **[How work flows](how-work-flows.md)**: what happens inside a chat turn, a workflow run and an email that becomes a case.
