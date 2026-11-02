"""The flag registry and how the install config sets it (c-611)."""

from __future__ import annotations

import re
from typing import get_args

import pytest
from pydantic import ValidationError

from ops_service_kit.flags import FLAGS, NAMES, FlagName, Flags
from ops_service_kit.settings import Settings


def test_every_flag_names_its_card_and_when_it_goes() -> None:
    for flag in FLAGS:
        assert re.fullmatch(r"c-\d+", flag.card), f"{flag.name} names no owning card"
        for text in (flag.description, flag.remove_when):
            assert text.strip() and "\n" not in text, f"{flag.name} needs a one-line description and removal note"


def test_the_name_type_and_the_registry_hold_the_same_names() -> None:
    assert set(get_args(FlagName)) == NAMES
    assert len(NAMES) == len(FLAGS)


def test_flags_are_off_unless_the_install_config_names_them(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_FLAGS", raising=False)
    assert not Settings().feature_flags.on("mcp_gateway")
    monkeypatch.setenv("OPS_FLAGS", '["mcp_gateway"]')
    assert Settings().feature_flags.on("mcp_gateway")


@pytest.mark.parametrize("value", ["mcp_gateway", " mcp_gateway , ", '["mcp_gateway"]'])
def test_the_install_config_names_flags_with_commas_or_a_json_list(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OPS_FLAGS", value)
    assert Settings().feature_flags.turned_on == {"mcp_gateway"}


@pytest.mark.parametrize("value", ["mcp_gatway", "mcp_gateway,mcp_gatway", '["mcp_gatway"]'])
def test_an_unknown_flag_in_the_install_config_stops_start_up(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OPS_FLAGS", value)
    with pytest.raises(ValidationError, match=r"unknown flag mcp_gatway in OPS_FLAGS; known flags: .*mcp_gateway"):
        Settings()


def test_reading_a_flag_the_registry_does_not_hold_fails() -> None:
    with pytest.raises(KeyError):
        Flags().on("mcp_gatway")  # pyright: ignore[reportArgumentType]


def test_the_resolved_answer_lists_every_flag() -> None:
    assert Flags(frozenset({"mcp_gateway"})).resolved() == [
        {"name": f.name, "description": f.description, "on": f.name == "mcp_gateway"} for f in FLAGS
    ]
