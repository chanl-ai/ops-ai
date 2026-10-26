# Ops AI SDK for Python

Calls the Ops AI platform's public API from Python: agents, workflows, runs, human tasks, cases, tools, knowledge and
files, with an API key acting in one team. Full guide: https://opsai.chanl.ai/docs/sdk/python

```bash
pip install ops-ai   # not published yet: install from this folder with `pip install ./sdk/python`
```

```python
from ops_ai import OpsAI

ops = OpsAI(api_key="ok_...", base_url="https://ops.example.com", team="team_claims")
run = ops.runs.start("wf_card_dispute", input={"account": "123"})
run = ops.runs.wait(run["runId"])  # returns when the run ends or stops at a human task
if run.get("taskId"):
    ops.tasks.decide(run["taskId"], "approve")
```

`AsyncOpsAI` has the same surface with every call awaited. Any public operation without a named method is
`ops.raw.<service>.<operationId>(...)`. The address, key and team can also come from `OPS_BASE_URL`, `OPS_API_KEY`
and `OPS_TEAM`, or from the profile `ops login` saves.

The `_generated` folder is written by `sdk/generate.py` from the services' OpenAPI documents; run `make sdk` after a
route changes, and `make sdk-check` fails until you do.
