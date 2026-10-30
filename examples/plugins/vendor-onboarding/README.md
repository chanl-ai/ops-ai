# Vendor onboarding: an example Ops AI plugin

A plugin a developer can copy: it checks a new supplier against a company registry, scores its risk in Python, asks
an agent for notes and stops for a person to approve. The full guide, including what changes when the plugin system
lands and the gaps found, is [docs/guide/vendor-onboarding-plugin.md](../../../docs/guide/vendor-onboarding-plugin.md).

YAML declares and wires; Python holds logic.

| Path | What it is |
|---|---|
| `plugin.yaml` | The manifest: what the plugin brings and what it needs |
| `contributions/tool-modules/vendor-registry/module.yaml` | A REST tool module, its secret header and its test-run mocks |
| `contributions/code-modules/vendor-scoring.yaml` | The function's inputs, the one tool it may call, and its limits |
| `contributions/functions/score_vendor.py` | The developer's `main.py`: `main(input)` runs in the code sandbox |
| `contributions/agents/vendor-reviewer.yaml` | The agent the workflow's AI step runs |
| `contributions/workflows/vendor-onboarding.yaml` | Look up, score, notes, human review, end |
| `fake_api/vendor_registry.py` | The fake registry the module describes |
| `tests/` | pytest for the function, and a check that the mocks match the fake registry |
| `install.py` | Installs into one team through the public APIs, then tries a run |
| `docs/` | The screenshot script and a finished run (`run-finished.png`) |

From the ops-ai root:

```bash
uv run pytest -q -p no:cacheprovider examples/plugins/vendor-onboarding/tests
uv run python examples/plugins/vendor-onboarding/install.py install   # a running stack with the sample team
uv run python examples/plugins/vendor-onboarding/install.py run
```

The plugin system is proposed, not built: `install.py` reads `plugin.yaml` itself. See the guide for an isolated stack.
