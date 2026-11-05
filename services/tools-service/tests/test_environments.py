"""One list of environments, by failure mode: a route accepts an environment the list does not have, or the
list has one no route accepts; a run kind reads as an environment ("production") rather than as a run (live)."""

from __future__ import annotations

from typing import get_args

from ops_tools.environments import ROWS, ModuleEnvironment, RunKind


def test_every_environment_a_route_accepts_is_a_row_of_the_one_list() -> None:
    assert set(get_args(ModuleEnvironment)) == {r.id for r in ROWS}
    assert set(get_args(RunKind)) == {"test", "live"}
    assert {r.id for r in ROWS if r.runs} == {"test", "production"}
    assert [r.id for r in ROWS if r.production] == ["production"]
