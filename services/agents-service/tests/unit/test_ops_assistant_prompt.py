"""The Ops Assistant's core prompt, by failure mode: it grows past its budget as rules are added; it names an app, team
or record type, so a rule for one team or app routes every team's asks; it names a tool the assistant does not hold,
which the model then calls or searches for; the tool cap leaves no room for independent reads in one step."""

from __future__ import annotations

import re

from ops_agents.api.ops_tools import ASSISTANT_FRAGMENTS, BUILT_IN_READS, OPS_ASSISTANT, TOOLS

# The core's share of the prompt (smart-assistant.html, Skills): under 2,000 tokens in all before history.
CORE_TOKENS = 700
# Four characters a token over-counts English for the models the assistant runs on (o200k_base reads the core as about
# 380), so the budget holds without a tokenizer download in CI.
CHARS_PER_TOKEN = 4
# The kernel's own tools and the memory search agents-service adds; the assistant may name these too.
BUILT_INS = {"present", "search_tools", "load_skill", "search_memory"}
# Apps, teams and record types: a core that names one routes by a rule written for one team or app, where routing must
# come from the turn's apps and skills (assistant-routing.html).
APPS = ("Salesforce", "Calendar", "GitHub", "Jira", "nCino", "HubSpot", "ServiceNow", "Zendesk", "Outlook", "Google")
TEAMS = ("Wealth", "Lending", "Risk", "Marketing", "Operations", "Harbor", "Northfield")
RECORD_TYPES = (
    "case",
    "task",
    "run",
    "workflow",
    "account",
    "opportunity",
    "event",
    "meeting",
    "application",
    "loan",
    "policy",
    "review",
    "client",
    "contact",
    "ticket",
    "incident",
)


def test_the_core_stays_within_its_budget() -> None:
    core = "\n\n".join(ASSISTANT_FRAGMENTS.values())
    assert len(core) / CHARS_PER_TOKEN <= CORE_TOKENS, len(core)


def test_the_core_names_no_app_team_or_record_type() -> None:
    core = " ".join(ASSISTANT_FRAGMENTS.values())
    named = [n for n in (*APPS, *TEAMS) if re.search(rf"\b{n}\b", core)]
    types = [t for t in RECORD_TYPES if re.search(rf"\b{t}s?\b", core, re.IGNORECASE)]
    assert named == [] and types == [], (named, types)


def test_every_tool_the_core_names_is_one_the_assistant_holds() -> None:
    named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", " ".join(ASSISTANT_FRAGMENTS.values())))
    assert named - (set(TOOLS) | set(BUILT_IN_READS) | BUILT_INS) == set()


def test_the_seed_serves_the_core_fragments_and_room_for_reads_in_one_step() -> None:
    assert [f["text"] for f in OPS_ASSISTANT["instructions"]] == list(ASSISTANT_FRAGMENTS.values())
    assert OPS_ASSISTANT["max_tool_calls"] == 6
