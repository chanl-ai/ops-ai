# Reads two outside JSON documents, whose shapes are checked by what it keeps rather than by types.
# pyright: basic
"""Refresh the model catalog snapshot (catalog/models.json) from models.dev, with LiteLLM's price and context table
filling what models.dev leaves out. models-service reads only the committed snapshot and never the network, so a
release runs on the catalog it was cut with; run this, review the diff, commit it.

    uv run python scripts/sync_catalog.py            # fetch both sources
    uv run python scripts/sync_catalog.py --from DIR # read DIR/models-dev.json and DIR/litellm.json instead

Kept: each provider catalog/knobs.json lists, its chat models that call tools, not deprecated. Each model's knobs
come from models.dev's flags (temperature, reasoning options) and the provider's `takes` list, with ranges and
defaults from knobs.json and the model's own output limit."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

MODELS_DEV = "https://models.dev/api.json"
LITELLM = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
CATALOG = Path(__file__).resolve().parents[1] / "catalog"
# Where LiteLLM keys each provider's models, after the bare id.
LITELLM_PREFIX = {"google": "gemini/", "azure": "azure/", "anthropic": "", "openai": "", "amazon-bedrock": ""}
FETCH_TIMEOUT_S = 60


def _litellm_row(table: dict[str, Any], provider: str, model_id: str) -> dict[str, Any]:
    for key in (model_id, f"{LITELLM_PREFIX.get(provider, '')}{model_id}"):
        if isinstance(found := table.get(key), dict):
            return found  # pyright: ignore[reportUnknownVariableType]
    return {}


def _knobs(provider: dict[str, Any], model: dict[str, Any], output: int | None) -> dict[str, Any]:
    takes: list[str] = provider["takes"]
    out: dict[str, Any] = {}
    sampling = bool(model.get("temperature"))
    for name in ("temperature", "top_p", "top_k"):
        if name in takes and sampling:
            out[name] = dict(provider.get(name) or {})
    if "max_tokens" in takes:
        limit = dict(provider.get("max_tokens") or {})
        if output:
            limit["maximum"] = output
            limit["default"] = min(int(limit.get("default") or output), output)
        out["max_tokens"] = limit
    for option in model.get("reasoning_options") or []:
        kind = option.get("type")
        if kind == "budget_tokens" and "thinking_budget" in takes:
            budget = {k: v for k, v in (provider.get("thinking_budget") or {}).items() if k != "wire"}
            if option.get("min"):
                budget["x-minimum-on"] = option["min"]
            cap = option.get("max") or (output - 1 if output else None)
            if cap:
                budget["maximum"] = cap
                budget["default"] = min(int(budget.get("default") or cap), cap)
            out["thinking_budget"] = budget
        if kind == "effort" and option.get("values") and "reasoning_effort" in takes:
            values = [str(v) for v in option["values"]]
            effort = dict(provider.get("reasoning_effort") or {})
            effort["enum"] = values
            if effort.get("default") not in values:
                effort["default"] = values[len(values) // 2]
            out["reasoning_effort"] = effort
    return out


def snapshot(models_dev: dict[str, Any], litellm: dict[str, Any], knobs: dict[str, Any]) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for pid, provider in knobs["providers"].items():
        kept: dict[str, Any] = {}
        for model_id, m in sorted((models_dev.get(pid) or {}).get("models", {}).items()):
            row = _litellm_row(litellm, pid, model_id)
            tools = m.get("tool_call", row.get("supports_function_calling", False))
            text_out = "text" in (m.get("modalities") or {}).get("output", ["text"])
            if not tools or not text_out or m.get("status") == "deprecated":
                continue
            limit = m.get("limit") or {}
            output = limit.get("output") or row.get("max_output_tokens")
            cost = m.get("cost") or {}
            input_price = cost.get("input")
            output_price = cost.get("output")
            if input_price is None and row.get("input_cost_per_token") is not None:
                input_price = round(row["input_cost_per_token"] * 1_000_000, 6)
            if output_price is None and row.get("output_cost_per_token") is not None:
                output_price = round(row["output_cost_per_token"] * 1_000_000, 6)
            kept[model_id] = {
                "name": m.get("name") or model_id,
                "context": limit.get("context") or row.get("max_input_tokens"),
                "output": output,
                "reasoning": bool(m.get("reasoning", row.get("supports_reasoning", False))),
                "toolCall": True,
                "images": "image" in (m.get("modalities") or {}).get("input", []),
                "inputPerMillion": input_price,
                "outputPerMillion": output_price,
                "knobs": _knobs(provider, m, output),
            }
        providers[pid] = kept
    return {
        "about": "Generated by scripts/sync_catalog.py from models.dev and LiteLLM; do not edit by hand.",
        "sources": {"modelsDev": MODELS_DEV, "litellm": LITELLM},
        "syncedAt": datetime.now(UTC).date().isoformat(),
        "providers": providers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh catalog/models.json from models.dev and LiteLLM.")
    parser.add_argument("--from", dest="source", type=Path, help="read models-dev.json and litellm.json from here")
    args = parser.parse_args()
    if args.source:
        models_dev = json.loads((args.source / "models-dev.json").read_text())
        litellm = json.loads((args.source / "litellm.json").read_text())
    else:
        with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=True) as http:
            models_dev = http.get(MODELS_DEV).raise_for_status().json()
            litellm = http.get(LITELLM).raise_for_status().json()
    knobs = json.loads((CATALOG / "knobs.json").read_text())
    written = snapshot(models_dev, litellm, knobs)
    (CATALOG / "models.json").write_text(json.dumps(written, indent=1, sort_keys=True) + "\n")
    counts = {p: len(m) for p, m in written["providers"].items()}
    print(f"catalog/models.json: {counts}")


if __name__ == "__main__":
    main()
