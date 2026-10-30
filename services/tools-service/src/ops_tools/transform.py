"""Response transforms: a Jinja2 template an operation's owner writes, rendered over the parsed, masked and scrubbed
response as `data` before the agent sees it. A plain `{{ data.a.b }}` means the same as in Liquid; filters differ.

The environment is sandboxed (no attribute or method escapes such as `data.__class__`) and strict (an undefined
name is an error, not an empty string). One template runs on every call, so a render is bounded. The process bound is
the one that holds whatever the template does; the others refuse common cases fast and with a clear reason:
- the render runs in its own child process (forked from a forkserver), which is killed at DEADLINE_S or when its
  memory passes MEMORY_LIMIT, read from the parent (/proc on Linux, ps elsewhere); on Linux RLIMIT_AS also caps it.
  Per-operator checks cannot close this alone: string concatenation in a loop doubles past any one check;
- `range` totals at most RANGE_BUDGET items per render, so nested ranges cannot multiply;
- nothing builds a string past MAX_SIZE: `*`, `%`, the center/indent/format/replace filters and the str methods that
  pad, repeat or format (center, ljust, rjust, zfill, expandtabs, replace, format) are sized before they allocate,
  because one C-level call can take gigabytes before any later check sees it;
Error messages name the template's problem, never the response's values."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import re
import resource
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sized
from multiprocessing.connection import Connection
from typing import Any, cast

from jinja2 import StrictUndefined, TemplateError, pass_eval_context
from jinja2.exceptions import SecurityError, TemplateSyntaxError, UndefinedError
from jinja2.filters import do_center, do_format, do_indent, do_replace
from jinja2.sandbox import SandboxedEnvironment

# A transform shapes an answer for an agent; output beyond this is a mistake, not a response.
MAX_RENDERED = 64_000
RANGE_BUDGET = 10_000
MAX_SIZE = 100_000
DEADLINE_S = 1.0
MEMORY_LIMIT = 256 * 1024 * 1024


def _refuse(what: str) -> SecurityError:
    return SecurityError(f"{what} past {MAX_SIZE} characters is refused in a response transform.")


def _width(n: Any, what: str) -> None:
    if isinstance(n, int) and n > MAX_SIZE:
        raise _refuse(what)


def _format_spec(fmt: Any) -> None:
    # A width or precision in a %-format or {}-format string is the size it pads to.
    if isinstance(fmt, str) and any(int(m) > MAX_SIZE for m in re.findall(r"\d+", fmt)):
        raise _refuse("A format width")


def _replace_size(s: Any, old: Any, new: Any, count: Any = None) -> None:
    s, old, new = str(s), str(old), str(new)
    n = s.count(old) if old else len(s) + 1
    if isinstance(count, int) and count >= 0:
        n = min(n, count)
    if len(s) + n * (len(new) - len(old)) > MAX_SIZE:
        raise _refuse("A replace result")


def _center(value: Any, width: int = 80) -> str:
    _width(width, "Centring")
    return do_center(value, width)


def _indent(s: Any, width: int | str = 4, first: bool = False, blank: bool = False) -> str:
    lines = str(s).count("\n") + 1
    if (len(width) if isinstance(width, str) else width) * lines > MAX_SIZE:
        raise _refuse("Indenting")
    return do_indent(s, width, first, blank)


def _format(value: Any, *args: Any, **kwargs: Any) -> str:
    _format_spec(value)
    return do_format(value, *args, **kwargs)


@pass_eval_context
def _replace(eval_ctx: Any, s: Any, old: Any, new: Any, count: Any = None) -> str:
    _replace_size(s, old, new, count)
    return do_replace(eval_ctx, s, old, new, count)


class _Bounded(SandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**", "%"})

    def call(self, context: Any, obj: Any, /, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]
        # The sandbox hands str.format back wrapped (wrap_str_format); the bound method is under __wrapped__.
        owner: Any = getattr(getattr(obj, "__wrapped__", obj), "__self__", None)
        if isinstance(owner, str):
            name = getattr(obj, "__name__", "")
            if name in ("center", "ljust", "rjust", "zfill"):
                _width(args[0] if args else kwargs.get("width"), f"str.{name}")
            elif name == "expandtabs":
                size = args[0] if args else kwargs.get("tabsize", 8)
                if isinstance(size, int) and owner.count("\t") * size > MAX_SIZE:
                    raise _refuse("str.expandtabs")
            elif name == "replace":
                _replace_size(owner, *args, **kwargs)
            elif name in ("format", "format_map"):
                _format_spec(owner)
        return super().call(context, obj, *args, **kwargs)

    def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
        sizes = [len(cast(Sized, x)) for x in (left, right) if isinstance(x, (str, list, tuple))]
        if operator == "%":
            _format_spec(left)
        if operator == "**" and isinstance(right, int) and abs(right) > 64:
            raise SecurityError("An exponent above 64 is refused in a response transform.")
        counts = [x for x in (left, right) if isinstance(x, int)]
        if operator == "*" and sizes and counts and counts[0] * max(sizes) > MAX_SIZE:
            raise SecurityError(f"Repeating a value past {MAX_SIZE} items is refused in a response transform.")
        return super().call_binop(context, operator, left, right)


def bounded_environment() -> SandboxedEnvironment:
    """A sandboxed, strict environment with the size checks above: the one transforms render in, and the base the
    workflow formulas (expressions.py) evaluate in."""
    env = _Bounded(undefined=StrictUndefined, autoescape=False)
    env.filters.update(center=_center, indent=_indent, format=_format, replace=_replace)
    return env


_ENV = bounded_environment()


def _budgeted_range() -> Callable[..., Iterator[int]]:
    left = [RANGE_BUDGET]

    def bounded(*args: int) -> Iterator[int]:
        r = range(*args)
        left[0] -= len(r)
        if left[0] < 0:
            raise SecurityError(f"range() over {RANGE_BUDGET} items in one render is refused in a response transform.")
        return iter(r)

    return bounded


def problem(template: str) -> str | None:
    """Why `template` does not parse, or None when it does. Checked when the operation is saved."""
    try:
        _ENV.parse(template)
    except TemplateError as e:
        return f"The response transform does not parse: {e.message or type(e).__name__}."
    return None


def _why(e: BaseException) -> str:
    # These messages come from the template (a name, an attribute, the parser); anything else may quote the
    # response's own values, e.g. a KeyError naming a key taken from the data, so only its type is given.
    if isinstance(e, MemoryError):
        return "The response transform ran out of memory and was stopped."
    if isinstance(e, (UndefinedError, SecurityError, TemplateSyntaxError)):
        return f"The response transform failed: {type(e).__name__}: {e.message}"
    return f"The response transform failed: {type(e).__name__}."


def _child(conn: Connection, template: str, data: Any, settings: Any = None) -> None:
    """Runs in the render process: renders and sends ("ok", text) or ("error", why)."""
    if sys.platform.startswith("linux"):
        # Address space, not resident memory: generous, so the parent's resident check usually fires first.
        resource.setrlimit(resource.RLIMIT_AS, (4 * MEMORY_LIMIT, 4 * MEMORY_LIMIT))
    try:
        conn.send(
            ("ok", _ENV.from_string(template).render(data=data, settings=settings or {}, range=_budgeted_range()))
        )
    except BaseException as e:  # MemoryError included: the child reports, the parent never sees a traceback.
        conn.send(("error", _why(e)))
    finally:
        conn.close()


def _resident(pid: int) -> int:
    """The child's resident memory in bytes; 0 once it is gone."""
    try:
        if sys.platform.startswith("linux"):
            with open(f"/proc/{pid}/statm") as f:
                return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=1, check=False
        ).stdout
        return int(out.strip() or 0) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


_CTX = multiprocessing.get_context("forkserver")
_CTX.set_forkserver_preload(["ops_tools.transform", "ops_tools.expressions"])


def _run(template: str, data: Any, settings: Any = None) -> tuple[str, str]:
    """Blocking: renders in a child and watches it. Returns ("ok", text) or ("error", why)."""
    return watch(_child, (template, data, settings), "The response transform")


def watch(target: Callable[..., None], args: tuple[Any, ...], what: str) -> tuple[str, Any]:
    """Blocking: runs `target(conn, *args)` in a forkserver child, bounded by DEADLINE_S and MEMORY_LIMIT, and returns
    what it sends: ("ok", value) or ("error", why). `target` must be a module-level function (the child imports it);
    `what` names the work in the messages, e.g. "The response transform"."""
    receive, send = _CTX.Pipe(duplex=False)
    child = _CTX.Process(target=target, args=(send, *args), daemon=True)
    child.start()
    send.close()
    deadline = time.monotonic() + DEADLINE_S
    try:
        while True:
            if receive.poll(0.02):
                return cast(tuple[str, Any], receive.recv())
            if not child.is_alive():
                return "error", f"{what} stopped without an answer (out of memory)."
            if time.monotonic() > deadline:
                return "error", f"{what} ran past {DEADLINE_S:g} s and was stopped."
            if _resident(child.pid or 0) > MEMORY_LIMIT:
                return "error", f"{what} ran out of memory and was stopped."
    finally:
        if child.is_alive():
            child.kill()
        child.join(1)
        receive.close()


async def apply(template: str, data: Any, settings: Any = None) -> tuple[Any, str | None]:
    """The transformed output and None, or `data` unchanged and why the render failed. Rendered text that parses as
    JSON is returned as JSON, otherwise as the text. `data` must already be scrubbed of secrets. `settings` is a
    plugin's merged settings (c-564), read as `settings.<name>`; it holds no secret values."""
    kind, text = await asyncio.to_thread(_run, template, data, settings)
    if kind != "ok":
        return data, text
    if len(text) > MAX_RENDERED:
        return data, f"The response transform produced over {MAX_RENDERED} characters."
    try:
        return json.loads(text), None
    except ValueError:
        return text, None
