"""A step's rule check, by failure mode: a check that runs code, and a path to a missing value that raises instead
of failing the check.

The call under test is `ops_agent_kernel.expr.evaluate(text, scope) -> bool`, where `scope` holds the roots `result`
and `inputs`. A text the grammar refuses raises a `ValueError` (or a subclass of it)."""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest


def evaluate(text: str, result: Any = None, inputs: dict[str, str] | None = None) -> bool:
    expr: Any = importlib.import_module("ops_agent_kernel.expr")
    return expr.evaluate(text, {"result": result, "inputs": inputs or {}})


# `this` is a standard-library module nothing here imports, so finding it loaded means a check's text was executed.
REFUSED = [
    '__import__("this")',
    "result.__class__",
    "(lambda: result)()",
    '[__import__("this") for x in result]',
    "result.note == '" + "x" * 300 + "'",  # over 300 characters
    "not " * 13 + "true",  # deeper than 12
    "1 in [" + ", ".join(["1"] * 61) + "]",  # more than 60 nodes
]


def test_a_check_never_runs_code_and_a_missing_value_fails_it() -> None:
    sys.modules.pop("this", None)
    assert evaluate("result.amount <= 500", {"amount": 200}) is True
    assert evaluate("result.amount <= 500", {"amount": 900}) is False
    assert evaluate('lower(inputs.tier) == "gold" and len(result.charges) > 0', {"charges": [1]}, {"tier": "Gold"})

    for text in REFUSED:
        with pytest.raises(ValueError):
            evaluate(text, {"amount": 200})
    assert "this" not in sys.modules, "a refused check was executed"

    # A missing key or index is null, and a comparison with null is false: the check fails, it does not raise.
    assert evaluate('result.customer.tier == "gold"', {}) is False
    assert evaluate("result.charges[3].amount > 1", {"charges": []}) is False
    assert evaluate("result.amount <= 500", None) is False
    assert evaluate("result.customer is null", {}) is True
