"""An app's first address on a host the tenant has not listed (c-616 S13): instead of refusing it, tools-service asks
the Security team in Human Tasks and answers 202 with the run key, the task's id. Approving lists the host on the
tenant's allow-list (`/v1/egress/held-hosts/decisions`), and the person's screen retries what it was doing; refusing
keeps the reason on the task, and a retry is refused with it."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Envelope, Out


class HostHeld(Exception):
    """Raised before anything is saved: the address waits on Security's task `run_key`."""

    def __init__(self, host: str, run_key: str) -> None:
        super().__init__(host)
        self.host = host
        self.run_key = run_key


class HeldHost(Out):
    held_for: Literal["security"]
    host: str
    # The Security task's id: read it in Human Tasks, retry once it is approved.
    run_key: str


# The 202 a route that may first set an app's address documents beside its own answer.
HELD: dict[int | str, dict[str, Any]] = {
    202: {"model": Envelope[HeldHost], "description": "The host is not listed; a Security admin was asked"}
}


def refused(host: str, task: dict[str, Any]) -> Unprocessable:
    reason = str(task.get("decisionReason") or "no reason given")
    return Unprocessable(
        f"Security refused {host} ({task['id']}): {reason}. An admin on the Security team can still list it under "
        "Egress.",
        code="egress_host_refused",
        details={"host": host, "runKey": task["id"], "reason": reason},
    )


def install_held_hosts(app: FastAPI) -> None:
    async def held(_: Request, e: Exception) -> JSONResponse:
        assert isinstance(e, HostHeld)
        data = {"heldFor": "security", "host": e.host, "runKey": e.run_key}
        return JSONResponse({"success": True, "data": data}, status_code=202)

    app.add_exception_handler(HostHeld, held)
