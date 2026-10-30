"""Combine facts' disagree port (c-535), by failure mode: sources that disagree going on by `out` when the step asks
for its own way; sources that agree taken down `disagree`; the port offered when the step did not ask for it; and the
field picker not knowing the port."""

from __future__ import annotations

from ops_engine.compiler import data_combine
from ops_engine.definition import NodeInstance
from ops_engine.node_types import default_registry
from ops_engine.shapes import BUILDERS
from tests.test_extract_read import Lookups
from tests.test_switch_combine import call

COMBINE = default_registry().get("ops.data.combine", 1)
LETTER: dict[str, object] = {"debtor": "Marcus Bell", "balance": "1,200.00"}
BANK_AGREES: dict[str, object] = {"debtor": "marcus bell", "balance": 1200}
BANK_DIFFERS: dict[str, object] = {"debtor": "Marcus Bell", "balance": 950}


def params(bank: dict[str, object], on: str | None) -> dict[str, object]:
    p: dict[str, object] = {
        "sources": [{"name": "letter", "values": LETTER}, {"name": "bank", "values": bank}],
        "fields": [{"field": "balance", "type": "money"}],
    }
    return p | ({"onDisagreement": on} if on else {})


def test_the_disagree_port_exists_only_when_the_step_asks_for_it() -> None:
    assert COMBINE.output_ports(params(BANK_AGREES, None)) == ["out"]
    assert COMBINE.output_ports(params(BANK_AGREES, "continue")) == ["out"]
    assert COMBINE.output_ports(params(BANK_AGREES, "port")) == ["out", "disagree"]


async def test_sources_that_disagree_leave_by_disagree_and_sources_that_agree_go_on() -> None:
    differs = await data_combine(call("ops.data.combine", params(BANK_DIFFERS, "port")))
    agrees = await data_combine(call("ops.data.combine", params(BANK_AGREES, "port")))
    unasked = await data_combine(call("ops.data.combine", params(BANK_DIFFERS, None)))
    assert differs.port == "disagree" and [c["field"] for c in differs.out["conflicts"]] == ["balance"], differs
    assert agrees.port == "out" and agrees.out["hasConflicts"] is False, agrees
    assert unasked.port == "out" and unasked.out["hasConflicts"] is True, "without the option it goes on, as today"


async def test_the_field_picker_offers_the_same_values_on_the_disagree_port() -> None:
    node = NodeInstance.model_validate(
        {"id": "combine", "type": "ops.data.combine", "typeVersion": 1, "parameters": params(BANK_AGREES, "port")}
    )
    shaped = await BUILDERS[COMBINE.executor](node, COMBINE, Lookups())  # type: ignore[arg-type]
    assert set(shaped) == {"out", "disagree"} and shaped["disagree"] == shaped["out"], shaped
