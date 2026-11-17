"""The guest's entry, run as /app/main.py inside the sandbox (never imported by the runner): it reads one request
line, runs the function with `ops` in scope, and writes one result or error line. `print` goes to stderr, the run's
log, so the function cannot write on the call channel."""

import json
import sys
import traceback
import types
from typing import Any, cast

_chan_in, _chan_out = sys.stdin, sys.stdout
sys.stdout = sys.stderr

# A line on the call channel. The guest has the standard library only, so the shape is named here.
type Json = bool | int | float | str | list[Json] | dict[str, Json] | None


def _send(message: dict[str, Json]) -> None:
    _chan_out.write(json.dumps(message) + "\n")
    _chan_out.flush()


class OpsError(Exception):
    """A refused or failed `ops.call`, with the gateway's code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Secret:
    """A handle to a secret this tool may use. Its value never enters the sandbox: the gateway puts it into a bound
    call's query when that call runs."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<secret {self.name}>"


def _wire(value: Any) -> Any:
    if isinstance(value, Secret):
        return {"$secret": value.name}
    if isinstance(value, dict):
        items = cast(dict[Any, Any], value)
        return {str(k): _wire(v) for k, v in items.items()}
    if isinstance(value, list | tuple):
        return [_wire(v) for v in cast(list[Any], value)]
    return value


# A value a function passes to `ops.call`: JSON, with a `Secret` handle anywhere a value goes.
type Arg = bool | int | float | str | Secret | list[Arg] | tuple[Arg, ...] | dict[str, Arg] | None


class Ops:
    def call(self, tool: str, args: dict[str, Arg] | None = None) -> Any:
        """Calls a tool this function is bound to, as the caller's own gateway call, and returns its output."""
        _send({"call": str(tool), "args": _wire(args or {})})
        reply: dict[str, Json] = json.loads(_chan_in.readline())
        if not reply.get("ok"):
            error = reply.get("error")
            if not isinstance(error, dict):
                error = {}
            raise OpsError(str(error.get("code", "call_failed")), str(error.get("message", "")))
        return reply.get("output")

    def secret(self, name: str) -> Secret:
        return Secret(str(name))


def _main() -> None:
    request: dict[str, Json] = json.loads(_chan_in.readline())
    # The function's source runs as a module named `tool`, with `ops` and `OpsError` in its namespace.
    tool = types.ModuleType("tool")
    tool.__dict__.update(ops=Ops(), OpsError=OpsError)
    try:
        exec(compile(str(request["source"]), "tool.py", "exec"), tool.__dict__)
        output = tool.__dict__[str(request["entry"])](request["input"])
        json.dumps(output)
    except MemoryError:
        _send({"error": {"code": "memory_limit", "message": "The function used more memory than its limit."}})
    except OpsError as e:
        traceback.print_exc()
        _send({"error": {"code": e.code, "message": e.message}})
    except BaseException as e:
        traceback.print_exc()
        _send({"error": {"code": "function_error", "message": f"{type(e).__name__}: {e}"[:500]}})
    else:
        _send({"result": output})


_main()
