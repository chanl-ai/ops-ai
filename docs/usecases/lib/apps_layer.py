"""The SDK's layer in the screen's words (an earlier change K1): `ops.apps`, `ops.credentials`, `ops.accounts`, `ops.tools`,
`ops.resources`, `ops.usage`, each a thin set of methods over the generated clients, which call today's routes.

A use case's sdk step asks for a method by area and verb; while K1 is not built the method is missing, the step's
check fails naming the task, and the script goes on to its next step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def layer(ops: Any, area: str, verb: str) -> Callable[..., Any] | None:
    """`ops.<area>.<verb>`, or None while the layer does not have it."""
    return getattr(getattr(ops, area, None), verb, None)


def run_path(module_id: str, operation: str) -> str:
    """A tool's run route (an earlier change P1): Mock or Real from the tool page, Real through the gateway's checks."""
    return f"/v1/tool-modules/{module_id}/operations/{operation}/run"


def attempt(ops: Any, area: str, verb: str, *args: Any, **kwargs: Any) -> Any:
    """`ops.<area>.<verb>(...)`, or None when the layer lacks it or the call raises (a resource the SDK already had
    under that name answers another shape until K1), so one target step never stops the script."""
    fn = layer(ops, area, verb)
    if fn is None:
        return None
    try:
        out = fn(*args, **kwargs)
        return list(out) if hasattr(out, "__next__") else out
    except Exception as e:  # a target step's failure is reported by its check, not raised
        print(f"note: ops.{area}.{verb} raised {type(e).__name__}: {str(e)[:160]}", flush=True)
        return None
