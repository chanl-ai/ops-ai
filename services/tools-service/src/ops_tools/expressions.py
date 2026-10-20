"""Workflow formulas (the Calculate step, `ops.data.compute`): named expressions over a step's values, e.g.
`min(levy.amount, balance)` or `business_days(levy.served, 20)`, evaluated in the response transforms' sandbox.

Each formula is a Jinja2 expression compiled to its typed value, so a number stays a number. Formulas run in the
order given and each sees the values and the formulas before it by name. The whole evaluation runs in one bounded
child (transform.watch: DEADLINE_S, MEMORY_LIMIT); the environment reaches no attribute escapes, no files and no
network, and a result that is not JSON is refused. Error messages name the formula and the expression's problem,
never the values it read."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import date, timedelta
from multiprocessing.connection import Connection
from typing import Any, cast

from jinja2 import TemplateError, Undefined
from jinja2.exceptions import SecurityError, TemplateSyntaxError, UndefinedError

from .transform import MAX_RENDERED, bounded_environment, watch

MAX_FORMULAS = 50
MAX_FORMULA = 2_000


def _day(value: Any) -> date:
    """A date from an ISO date or date-time text (its first ten characters) or a date."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError("a date must be an ISO date such as 2026-10-19") from None


def business_days(start: Any, days: int) -> str:
    """The date `days` working days after `start` (Monday to Friday; public holidays are not counted out)."""
    day, step, left = _day(start), (1 if days >= 0 else -1), abs(int(days))
    if left > 10_000:
        raise ValueError("business_days counts at most 10000 days")
    while left:
        day += timedelta(days=step)
        if day.weekday() < 5:
            left -= 1
    return day.isoformat()


def add_days(start: Any, days: int) -> str:
    return (_day(start) + timedelta(days=int(days))).isoformat()


def days_between(start: Any, end: Any) -> int:
    return (_day(end) - _day(start)).days


_ENV = bounded_environment()
# Jinja's stubs type globals as its own defaults only; any callable is a valid global.
FUNCTIONS: dict[str, Any] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sum": sum,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "floor": math.floor,
    "ceil": math.ceil,
    "business_days": business_days,
    "add_days": add_days,
    "days_between": days_between,
}
_ENV.globals.update(cast(Any, FUNCTIONS))


def problem(name: str, formula: str) -> str | None:
    """Why `formula` does not parse, or None when it does. Checked when a definition is saved."""
    if len(formula) > MAX_FORMULA:
        return f"{name}: a formula is at most {MAX_FORMULA} characters."
    try:
        _ENV.compile_expression(formula)
    except TemplateError as e:
        return f"{name}: the formula does not parse: {e.message or type(e).__name__}."
    return None


def _why(name: str, e: BaseException) -> str:
    # The template's own messages (a name, an attribute, the parser) and the date helpers' are safe to show; anything
    # else may quote a value the formula read, so only its type is given.
    if isinstance(e, MemoryError):
        return f"{name}: the formula ran out of memory."
    if isinstance(e, (UndefinedError, SecurityError, TemplateSyntaxError)):
        return f"{name}: {type(e).__name__}: {e.message}"
    if isinstance(e, ValueError) and str(e).startswith(("a date", "business_days")):
        return f"{name}: {e}"
    if isinstance(e, ZeroDivisionError):
        return f"{name}: division by zero."
    return f"{name}: the formula failed: {type(e).__name__}."


def _child(conn: Connection, formulas: list[tuple[str, str]], values: dict[str, Any]) -> None:
    """Runs in the evaluation process: sends ("ok", {name: value}) or ("error", why)."""
    scope = dict(values)
    out: dict[str, Any] = {}
    name = ""
    try:
        for name, formula in formulas:
            result = _ENV.compile_expression(formula, undefined_to_none=False)(**scope)
            if isinstance(result, Undefined):
                # The sandbox answers an unsafe attribute with an Undefined carrying its SecurityError; str() raises
                # it, so the message says which, and a plain missing name raises UndefinedError.
                str(result)
                conn.send(("error", f"{name}: the formula names something the values do not have."))
                return
            text = json.dumps(result)
            if len(text) > MAX_RENDERED:
                conn.send(("error", f"{name}: the result is over {MAX_RENDERED} characters."))
                return
            out[name] = scope[name] = json.loads(text)
        conn.send(("ok", out))
    except TypeError as e:
        why = "the result is not JSON" if "JSON serializable" in str(e) else "a value has the wrong type"
        conn.send(("error", f"{name}: {why}."))
    except BaseException as e:
        conn.send(("error", _why(name, e)))
    finally:
        conn.close()


async def evaluate(formulas: dict[str, str], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Each formula's value, by name, and None; or None and why one failed. `values` must already be resolved."""
    if len(formulas) > MAX_FORMULAS:
        return None, f"A step has at most {MAX_FORMULAS} formulas."
    for name, formula in formulas.items():
        if why := problem(name, formula):
            return None, why
    kind, result = await asyncio.to_thread(watch, _child, (list(formulas.items()), values), "The formula")
    return (result, None) if kind == "ok" else (None, str(result))
