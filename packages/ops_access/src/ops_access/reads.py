"""`reader_of(area)`: the read check every service mounts on a GET, so a read asks the grid's view cell the same way
everywhere. A person needs `<area>.view` in the team the request acts in (403 `forbidden`); a service token needs
`<area>:view`. An API key holds no view cell (`KEY_GRANTS`) and reads only what its routes give it, the runs it starts,
so it keeps its own path."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ops_identity import CurrentCaller, Principal

from .check import can


def reader_of(area: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(p: CurrentCaller) -> Principal:
        if p.kind != "api_key":
            can(p, area, "view", team=p.team_id or None, what=f"the team's {area}", code="forbidden")
        return p

    return dependency
