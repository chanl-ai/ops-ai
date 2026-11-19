# Quickstart

Status: current. The commands are the ones the repository's own quick start runs.

Run every service, the console and a built-in test model on your own machine, then build and run a workflow from a
folder and call it from Python. It takes about ten minutes and needs no model key and no network beyond the first
download. To install Ops AI on a server for a team instead, read [Install](install.md).

## What you need

| Tool | Used for |
|---|---|
| [uv](https://docs.astral.sh/uv/) | The services and the `opsai` command, on Python 3.12, which uv downloads when it is missing |
| Node 22 or newer and pnpm 10 (`npm install -g pnpm@10`) | The console |
| Docker with Compose, running | PostgreSQL, the policy engine and two test mail servers |
| Optional: [Tesseract](https://tesseract-ocr.github.io/) | Reading scanned files; without it `make health` shows documents as `degraded` |

One stack runs per machine. It uses ports 3016, 3017, 3020, 8700 to 8770, 8799, 8181, 5477, 3025, 3143, 1025 and 8025,
so stop anything else on them first.

## Start the stack

<!-- site: steps -->
1. **Clone and install.** `make install` runs `pnpm install` and `uv sync`, once per clone.

   ```bash
   git clone https://github.com/chanl-ai/ops-ai.git && cd ops-ai
   make install
   ```

2. **Start everything.** `make up` starts the database, applies every migration, starts each service, the worker and
   the console, and installs a sample team on a new database. With no `OPENAI_API_KEY` set, every model alias answers
   from the test model.

   ```bash
   make up
   make health
   ```

   `make health` lists each service with its port and state.

3. **Sign in.** Open <http://localhost:3016> and sign in as `w.kamau@harborpine.example` with the development password
   `northfield-demo`. The bank, its people and its customers are fictional sample data.

## Run your first workflow

<!-- site: steps -->
1. **Write a local profile.** Each example folder has a `setup.py` that signs in and writes `.ops-profile.json` into
   the folder: the service addresses, the team and a sign-in. Run it again when the sign-in expires.

   ```bash
   uv run python examples/workflows/01-normalize-a-request/setup.py
   ```

2. **Validate, save and run the workflow.** `OPS_CONFIG` points the `opsai` command at that profile; without it the
   command reads `~/.config/ops-ai/config.json`.

   ```bash
   cd examples/workflows/01-normalize-a-request
   OPS_CONFIG=.ops-profile.json uv run opsai workflows validate resources/workflow.yaml
   OPS_CONFIG=.ops-profile.json uv run opsai workflows apply resources/workflow.yaml
   OPS_CONFIG=.ops-profile.json uv run opsai workflows run normalize_support_request --input fixtures/valid.json --test --wait
   cd ../../..
   ```

3. **Call it from Python.** The profile gives the client everything it needs, so `OpsAI()` takes no arguments.

   ```bash
   OPS_CONFIG=$PWD/examples/workflows/01-normalize-a-request/.ops-profile.json uv run python -c "
   from ops_ai import OpsAI
   ops = OpsAI()
   run = ops.workflows.run('normalize_support_request', mode='test', wait=True,
       input={'customerEmail': 'ada@example.test', 'subject': 'Card', 'message': 'Where is my refund?'})
   print(run['status'], run.get('outcome'))
   "
   ```

   It prints `succeeded accepted`. Open the run in the console under **Agent Builder › Workflows › Runs**.

## Chat with an agent

```bash
make chat-agents AS=builder
make chat AS=builder AGENT='Branch Policy' SAY='What is the daily cash withdrawal limit at a branch?'
```

The answer streams to the terminal with a link to the same conversation in the console. On the test model the reply
repeats what the agent retrieved, which shows the knowledge search and its citations.

## Use a real model or stop

| Task | Do |
|---|---|
| Answer with a real model | Put `OPENAI_API_KEY` in a `.env` file at the repository root (git ignores it; `.env.example` lists the settings) and run `make up` again |
| Stop and keep the data | `make down KEEP_DB=1` |
| Call the API directly | The console at port 3016 does not serve the API. Each service serves its own part: platform 8710, agents 8700, tools 8720, kb 8740, files 8750, documents 8760, with one reference page for all of them at <http://localhost:8799> |

## Next

<!-- site: cards -->
- **[Build with Ops AI](build-with-ops-ai.md)**: the example folders in the order to try them, from one message to an agent that starts a workflow.
- **[Workflows](workflows.md)**: author, validate, publish and test-run a workflow from the SDK or the command line.
- **[Agents](agents.md)**: author, publish and chat with an agent.
- **[How work flows](how-work-flows.md)**: what happens inside a chat turn, a workflow run and an email that becomes a case.
