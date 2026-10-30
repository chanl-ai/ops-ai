# wf-builder: describe a workflow, get one that runs

Status: current. Proven by `make skills-proof`.

skill: wf-builder
description: Draw a workflow from what a developer describes, check it with the engine, create it on the profile they name and start a test run. Use when someone asks to build, sketch or draft a workflow, or types /wf-builder.
targets: python3 scripts/wf_builder.py, python3 scripts/wf_builder_examples.py --check, make usecase-test UC=uc-568 LAYER=cli

## What it does

A developer says what the workflow is for. The skill picks the seeded example closest to it, adapts the steps, writes
`workflows/<id>.json` beside the developer, has the engine on the named profile check it, and shows the steps and
every way out of each step. Nothing is created until the developer says so. The ops CLI is not built yet, so
`scripts/wf_builder.py` calls the Python SDK on the profile the developer names. Every command below runs as
`uv run --with-editable sdk/python python scripts/wf_builder.py ...` from the repository root, which brings in the SDK;
`python3 scripts/wf_builder.py` is short for that here.

## Steps

1. Ask which profile to use (`--profile`, from `~/.config/ops-ai/config.json` or `OPS_CONFIG`), unless they named
   one. Read the node types that profile serves: `python3 scripts/wf_builder.py catalog --profile <name>`. Use only
   those types; never write one from memory.
2. Read `docs/guide/skills/wf-builder/rules.md` and pick the closest example in
   `docs/guide/skills/wf-builder/examples.md`.
3. Write a goal file: the new workflow's `id`, the `goal` in the developer's words and the `example` to adapt, as
   `{"id": "invoice_po_match", "goal": "Compare an invoice with its purchase order and send a person any amount that
   differs.", "example": "two_source_match"}`. Then a dry run:
   `python3 scripts/wf_builder.py create --file goal.json --profile <name>`. It writes `workflows/<id>.json`, prints
   the steps and ports and the engine's checks, and creates nothing.
4. Edit `workflows/<id>.json` until it says what the developer asked, then
   `python3 scripts/wf_builder.py validate --file workflows/<id>.json --profile <name>` until it prints Valid.
5. Show the developer the steps and ports, and ask before creating. Then `create --file workflows/<id>.json --create`.
   On a profile that is not local (named other than `local`, or not on this machine) the script also asks for the
   workflow id typed back, and creates on nothing else.
6. Start a test run: `python3 scripts/wf_builder.py run <id> --input key=value ... --wait --profile <name>`. Report
   where it ended, where it waits for a person, and any field the sources disagree on.

## Proof

```bash proof
python3 scripts/wf_builder_examples.py --check
uv run --frozen pytest -q scripts/tests/test_wf_builder.py services/agents-service/tests/engine/test_seeds.py
```
