"""A step's rule check: a small expression over the step's result and the skill's inputs, read with `ast.parse` and
walked node by node. Nothing is compiled or executed, and a node the grammar does not name is refused.

The grammar: numbers, strings, `true`, `false`, `null` and lists of them; the roots `result` and `inputs`; `.field`
and `[integer]` paths (a missing key or index is null, never an error); comparisons, `in`, `is` against `true`,
`false` or `null`; `and`, `or`, `not`; arithmetic on numbers; and `len`, `lower`, `contains`, `exists`. A comparison
with null, or an ordered one on a value that is not a number, is false.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from typing import Any, Literal, TypedDict, cast

from ops_service_kit.http import Json, JsonValue


class Scope(TypedDict):
    """What a rule reads: the step's own result (a tool's output, or a sub-skill's exit and results) and the skill's
    inputs."""

    result: JsonValue
    inputs: Mapping[str, str]


MAX_CHARS = 300
MAX_NODES = 60
MAX_DEPTH = 12
ROOTS = ("result", "inputs")
LITERALS: dict[str, bool | None] = {"true": True, "false": False, "null": None}
FUNCTIONS = ("len", "lower", "contains", "exists")
# A text that names a root and then a path reads as a rule, whether or not it parses. `steps` is not a root: an
# earlier step's values are stored masked, so a rule reads only its own result and the inputs.
_ROOT_PATH = re.compile(r"\b(?:result|inputs|steps)(?:\.\w|\[)")


class CheckError(ValueError):
    """A check's text is outside the grammar."""


def _number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _parsed(text: str) -> ast.expr:
    if len(text) > MAX_CHARS:
        raise CheckError(f"A check is at most {MAX_CHARS} characters.")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise CheckError("The check is not a valid rule.") from e
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.expr)]
    if len(nodes) > MAX_NODES:
        raise CheckError(f"A check has at most {MAX_NODES} parts.")
    if _depth(tree.body) > MAX_DEPTH:
        raise CheckError(f"A check nests at most {MAX_DEPTH} deep.")
    return tree.body


def _depth(node: ast.AST) -> int:
    inner = [_depth(c) for c in ast.iter_child_nodes(node) if isinstance(c, ast.expr)]
    return 1 + max(inner, default=0)


def _allowed(node: ast.expr) -> None:
    """Refuses a node the grammar does not name, whatever the values would be: every branch is read, so a part an
    `and` or `or` would skip is checked too."""
    if isinstance(node, ast.Constant):
        if not (node.value is None or isinstance(node.value, bool | int | float | str)):
            raise CheckError("Only numbers and text are allowed as values.")
    elif isinstance(node, ast.Name):
        if node.id not in LITERALS and node.id not in ROOTS:
            raise CheckError(f"{node.id} is not something a check can read; use result or inputs.")
    elif isinstance(node, ast.List):
        for e in node.elts:
            _allowed(e)
    elif isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise CheckError(f"A check cannot read {node.attr}.")
        _allowed(node.value)
    elif isinstance(node, ast.Subscript):
        index = node.slice
        if not isinstance(index, ast.Constant) or not isinstance(index.value, int) or isinstance(index.value, bool):
            raise CheckError("An index is a whole number from 0, like result.items[0].")
        _allowed(node.value)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not | ast.USub):
            raise CheckError("That operator is not allowed in a check.")
        _allowed(node.operand)
    elif isinstance(node, ast.BoolOp):
        for v in node.values:
            _allowed(v)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, ast.Add | ast.Sub | ast.Mult | ast.Div):
            raise CheckError("Only + - * / are allowed in a check.")
        _allowed(node.left)
        _allowed(node.right)
    elif isinstance(node, ast.Compare):
        _allowed(node.left)
        for op, right in zip(node.ops, node.comparators, strict=True):
            if not isinstance(op, _COMPARISONS):
                raise CheckError("That comparison is not allowed in a check.")
            if isinstance(op, ast.Is | ast.IsNot) and not (isinstance(right, ast.Name) and right.id in LITERALS):
                raise CheckError("is and is not compare with true, false or null only.")
            _allowed(right)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
            raise CheckError(f"A check can call only {', '.join(FUNCTIONS)}.")
        wanted = 2 if node.func.id == "contains" else 1
        if len(node.args) != wanted:
            raise CheckError(f"{node.func.id} takes {wanted} value{'s' if wanted > 1 else ''}.")
        for a in node.args:
            _allowed(a)
    else:
        raise CheckError("That is not allowed in a check.")


_COMPARISONS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot)


class _Walker:
    """Evaluates a check `_allowed` has passed."""

    def __init__(self, scope: Scope) -> None:
        self.scope = scope

    def value(self, node: ast.expr) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return LITERALS[node.id] if node.id in LITERALS else cast(Json, self.scope).get(node.id)
        if isinstance(node, ast.List):
            return [self.value(e) for e in node.elts]
        if isinstance(node, ast.Attribute):
            held = self.value(node.value)
            return cast(Json, held).get(node.attr) if isinstance(held, dict) else None
        if isinstance(node, ast.Subscript):
            index = cast(int, cast(ast.Constant, node.slice).value)
            held = self.value(node.value)
            if isinstance(held, list) and 0 <= index < len(cast(list[Any], held)):
                return cast(list[Any], held)[index]
            return None
        if isinstance(node, ast.UnaryOp):
            v = self.value(node.operand)
            if isinstance(node.op, ast.Not):
                return not v
            return -v if _number(v) else None
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self.value(v) for v in node.values)
            return any(self.value(v) for v in node.values)
        if isinstance(node, ast.BinOp):
            return self._arithmetic(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        raise CheckError("That is not allowed in a check.")

    def _arithmetic(self, node: ast.BinOp) -> Any:
        left, right = self.value(node.left), self.value(node.right)
        if not (_number(left) and _number(right)):
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right if right else None

    def _compare(self, node: ast.Compare) -> bool:
        left = self.value(node.left)
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = self.value(right_node)
            if not self._holds(op, left, right):
                return False
            left = right
        return True

    def _holds(self, op: ast.cmpop, left: Any, right: Any) -> bool:
        if isinstance(op, ast.Is | ast.IsNot):
            same = left is right
            return same if isinstance(op, ast.Is) else not same
        if isinstance(op, ast.In | ast.NotIn):
            if left is None or not isinstance(right, list | str):
                return False
            if isinstance(right, str) and not isinstance(left, str):
                return False
            found = left in right
            return found if isinstance(op, ast.In) else not found
        if left is None or right is None:
            return False
        if isinstance(op, ast.Eq | ast.NotEq):
            # True is not 1: a yes or no value equals only a yes or no value.
            equal = left == right and isinstance(left, bool) == isinstance(right, bool)
            return equal if isinstance(op, ast.Eq) else not equal
        if not (_number(left) and _number(right)):
            return False
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        return left >= right

    def _call(self, node: ast.Call) -> Any:
        name, args = cast(ast.Name, node.func).id, [self.value(a) for a in node.args]
        if name == "exists":
            return args[0] is not None
        if name == "len":
            return len(cast(Any, args[0])) if isinstance(args[0], str | list | dict) else None
        if name == "lower":
            return args[0].lower() if isinstance(args[0], str) else None
        text, part = args
        return isinstance(text, str) and isinstance(part, str) and part in text


def _rule(text: str) -> ast.expr:
    tree = _parsed(text)
    _allowed(tree)
    return tree


# What `inputs_read` holds when a rule reads `inputs` whole (`len(inputs)`), not one of them by name.
EVERY_INPUT = "*"


def inputs_read(text: str) -> set[str]:
    """The inputs a rule reads, by name; `EVERY_INPUT` among them when it reads `inputs` whole. Raises `CheckError`
    for a text outside the grammar."""
    tree = _rule(text)
    named = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and _is_inputs(n.value)]
    whole = sum(1 for n in ast.walk(tree) if _is_inputs(n)) > len(named)
    return {*named, EVERY_INPUT} if whole else set(named)


def _is_inputs(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "inputs"


def evaluate(text: str, scope: Scope) -> bool:
    """Whether the rule holds for `scope` (`result`, `inputs`). Raises `CheckError` for a text outside the grammar."""
    return bool(_Walker(scope).value(_rule(text)))


def kind_of(text: str) -> Literal["rule", "model"]:
    """Who judges a check: `rule` when the text is a valid rule, `model` when it is a sentence. A text that reads as
    a rule and is not a valid one raises `CheckError`: stored as a sentence, a typing mistake would turn a check the
    runtime enforces into one the model judges."""
    try:
        tree = _parsed(text)
    except CheckError:
        if len(text) <= MAX_CHARS and not _ROOT_PATH.search(text):
            return "model"
        raise
    shaped = any(isinstance(n, ast.Compare | ast.Call) for n in ast.walk(tree))
    named = any(isinstance(n, ast.Name) and n.id in (*ROOTS, "steps") for n in ast.walk(tree))
    if not shaped and not named:
        return "model"
    _allowed(tree)
    return "rule"
