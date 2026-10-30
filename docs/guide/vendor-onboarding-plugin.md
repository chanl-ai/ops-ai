# Building a plugin: the vendor-onboarding example

Status: current, 2026-10-29. The example installs and runs on a local stack today through the public APIs. The plugin
system it is written for is proposed and not built (`the planning repo/docs/plans/ops-ai/plugins.html`). The example lives
in `examples/plugins/vendor-onboarding/`; every path below is relative to that folder unless it says otherwise.

A team that buys from suppliers checks each new one before it is paid: is the company real and active, is it on a
sanctions list, how much risk does it carry. This plugin brings that check as one thing a team installs: a REST tool
module for a company registry, a Python function that scores the supplier, an agent that writes notes for the
approver, and a workflow that wires them together and stops for a person to approve or reject.

## What a plugin is

A plugin is a versioned bundle of records a team would otherwise build one at a time in the console: tool modules,
code functions, agents, workflows, and later skills, guardrails, case types and knowledge. Installing it writes the
team's own copies, each published through the review that kind of record always needs. The design, including
acceptance by the platform admin and signed bundles, is in `plugins.html`.

## Layout

| Path | What it is | Who reads it |
|---|---|---|
| `plugin.yaml` | The manifest: id, version, what the plugin contributes, what it requires (a secret, a model, an approver) and the egress host it needs | `install.py` today; the plugin system later |
| `contributions/tool-modules/vendor-registry/module.yaml` | The registry's two REST operations, their secret header and their test-run mocks | tools-service `POST /v1/tool-modules` |
| `contributions/code-modules/vendor-scoring.yaml` | The function's name, inputs, the one tool it may call, and its time, memory and call limits | tools-service `POST /v1/tool-modules` (`type: code`) |
| `contributions/functions/score_vendor.py` | The scoring logic, in Python | runner-service, the code sandbox |
| `contributions/agents/vendor-reviewer.yaml` | The agent the AI step runs | agents-service `POST /v1/agents` |
| `contributions/workflows/vendor-onboarding.yaml` | The workflow: look up, score, notes, human review, end | agents-service `POST /v1/workflows/definitions` |
| `fake_api/vendor_registry.py` | A fake company registry, the outside system the module describes | tests, and you, locally |
| `tests/` | `test_score_vendor.py` tests the function; `test_fake_api.py` keeps the mocks equal to the fake registry | pytest |
| `install.py` | Installs the plugin into one team and tries it | you, until the plugin system exists |
| `docs/` | `screenshot.mjs` and the finished run it captured, `run-finished.png` | people |

## Code or YAML

YAML declares and wires; Python holds logic. The YAML files are the request bodies the services already accept, so
everything a YAML file says can also be done in the console.

| You want to | Write it in |
|---|---|
| Call an outside system's REST API | YAML: the operation's method, URL, inputs and secret header (`module.yaml`) |
| Work something out: a score, a rule, a calculation | Python: a function in `functions/`, run in the sandbox |
| Let that function reach a system | YAML: name the operation under `bindings`; the function calls it with `ops.call` |
| Ask a model | YAML: an agent file, and an `ops.ai.*` step in the workflow |
| Decide the order of steps, branches and who approves | YAML: the workflow |
| Tune a threshold per team | YAML: pass it as the step's input (`policy`), with the function's defaults as the fallback |

So yes, a developer writes a `main.py`. In this plugin it is `contributions/functions/score_vendor.py`:

- The runner calls `main(input)` with the workflow step's mapped input and puts `ops` in scope. `ops.call(tool, args)`
  calls an operation listed in `bindings`, as the run's own call, so egress, approvals and test mocks apply to it as
  they would to a workflow step. `ops.secret(name)` hands a team secret to a bound call by name; its value never
  enters the sandbox.
- The sandbox is Python 3.12 on WASM with no network, no files and no installed packages, so the function uses the
  language's built-ins only and returns something JSON can encode.
- Keep the logic in a plain function (`score` here) that `main` calls after its `ops.call`s, so it is unit-tested
  without a stack.

## Run the function's tests

From the ops-ai repository root, no stack needed:

```bash
uv run pytest -q -p no:cacheprovider examples/plugins/vendor-onboarding/tests
```

`test_score_vendor.py` loads the function file by path, as the runner does, and gives `main` a fake `ops`. It has one
test per way the scoring can be wrong. `test_fake_api.py` checks every mock in `module.yaml` against the fake
registry.

## Install it on a local stack today

There is no `ops plugin pack`, no acceptance by the platform admin and no install from Connections yet. `install.py`
does by hand what the install process will do: it reads `plugin.yaml`, makes each contribution through the same public
routes `scripts/sample_team.py` uses, replaces each `@kind/id` reference with the id the team got, and publishes each
record through its review. Nothing is written to a database directly. A second run prints FOUND for everything.

An isolated stack (ports +1000) with the fake model, the worker and the sample team's people:

```bash
OPS_STACK_FAKES=1 make up ISOLATED=1 AUTH=platform DEMO_MODEL=fake
OPS_STACK_FAKES=1 make sample-team ISOLATED=1 DEMO_MODEL=fake

export OPS_CONSOLE_PORT=4016 OPS_PLATFORM_PORT=9710 OPS_AGENTS_PORT=9700 OPS_TOOLS_PORT=9720 \
  OPS_KB_PORT=9740 OPS_FILES_PORT=9750 OPS_DOCUMENTS_PORT=9760 OPS_RUN_DIR=$PWD/.run/isolated
uv run python examples/plugins/vendor-onboarding/install.py install
uv run python examples/plugins/vendor-onboarding/install.py run
```

On the shared stack (<http://localhost:3016>) with the sample team, leave the exports out. Pass `--model` an alias that
stack runs on the fake model; the default, `bank-assist`, is the sample team's.

What `install` does, in order:

1. Adds `registry.vendors.test` to the workspace's egress list, as a Security admin (a module may only name a listed
   host).
2. Sets `VENDOR_REGISTRY_KEY` as the team's secret, from the environment or `dev-registry-key`.
3. Makes the Vendor registry module with its two operations, has Security publish it, and adds its test-run mocks.
4. Makes the Vendor scoring code module with the function's source, and has Security publish it.
5. Makes the Vendor Reviewer agent on the given model alias and publishes it.
6. Saves the workflow and publishes it.

`run` starts the workflow as a test run for a sample supplier, prints the lookup, score and notes, decides the human
review as the approver (Riley Chen) and waits for the run to end. `--vendor '{...}'` tries another supplier;
`"legalName": "Sable Freight Partners"` is on the fake sanctions list and scores `blocked`. Open the run in the console
under Workflows > Runs.

Proof from 2026-10-29 on an isolated stack: run `wfrun_6a12e0c6c806` looked the company up, scored it 90 (`low`, "Trading
for 3 years, under 5.") in the sandbox, got the agent's notes, waited for Riley Chen, who approved, and ended
`succeeded` with outcome `onboarded` (`docs/run-finished.png`). Run `wfrun_671f436d86d9` with the sanctioned name scored
`blocked` with one screening hit, was rejected and ended `declined`.

## What changes when the plugin system lands

| Today | With plugins (`plugins.html`) |
|---|---|
| `install.py` reads `plugin.yaml` and calls each service | `ops plugin pack` makes a signed bundle; the platform admin accepts it; a team admin installs it from Connections, and a central install process calls each owner service |
| References are resolved by text replacement in `install.py` | The install plan resolves `@kind/id` in dependency order and records each copy's provenance |
| Records are found again by name | Each copy carries the plugin, version and baseline it came from, so an update can tell an edited copy from an untouched one |
| Egress, the secret and the model alias are set by the script | They are declared requirements, bound in the install dialog and agreed to at acceptance |
| Nothing can be updated or removed as one | Updates open the newer version as the copies' next draft; removal checks what still uses each copy |

The files under `contributions/` stay as they are: they are already the bodies each service accepts.

## Gaps found

Found while building and running this example on 2026-10-29. None was worked around inside the platform.

| Gap | Effect here |
|---|---|
| Nothing reads `plugin.yaml`: no pack, acceptance, install plan or provenance | `install.py` interprets the manifest by hand |
| tools-service imports an OpenAPI document only from a URL; an uploaded or bundled one answers "not available yet" (`services/tools-service/src/ops_tools/modules/service.py`, `_discover`) | The registry is described as hand-built HTTP operations in YAML, not as the OpenAPI document a plugin would carry |
| A local stack cannot reach a plugin's own fake API: tools-service calls https on port 443 only, to a listed host, and the dev host-to-address map (`OPS_EGRESS_RESOLVE`) and trusted CA are fixed when tools-service starts, read from the shared `.env`, which overrides the environment | Runs are test runs answered by the module's mocks; `fake_api/` is reached by the tests only. A live run would fail to connect |
| On the fake model, an AI step with an answer schema (`ops.ai.summarise`, `classify`, `extractText`, `draft`, or an agent step with `outputSchema`) takes its error port unless the stack's fake script has a rule for that prompt, and a plugin cannot bring rules | The workflow uses an agent step with no answer schema; its notes on the fake model are the fake's echo of the prompt |
| A hand-built HTTP operation's inputs are all inferred as required strings from its URL and body placeholders | `screen_vendor` takes `legal_name` and `country` as strings; typing them needs a later `PATCH` of the operation |
| Workflow ids are unique in the workspace and belong to the first team that saves one (`scripts/sample_team.py` at the repo root, `prefixed`) | A second team installing this plugin would collide on `vendor_onboarding`; `install.py` does not prefix ids |
| `make up ISOLATED=1` starts neither the worker nor the fakes, and services stay on dev sign-in, which refuses the sample installer's tokens | The isolated stack needs `OPS_STACK_FAKES=1` and `AUTH=platform`, which the sample-team guide does not say |
