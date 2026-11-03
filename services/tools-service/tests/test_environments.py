"""One list of environments (c-580), by failure mode: a route accepts an environment the list does not have, or the
list has one no route accepts."""

from __future__ import annotations

from typing import get_args

from ops_tools.environments import ROWS, ModuleEnvironment, RunKind


def test_every_environment_a_route_accepts_is_a_row_of_the_one_list() -> None:
    assert set(get_args(ModuleEnvironment)) == {r.id for r in ROWS}
    assert set(get_args(RunKind)) == {r.id for r in ROWS if r.runs}
    assert [r.id for r in ROWS if r.production] == ["production"]
