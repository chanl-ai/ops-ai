"""The apps line: which apps the team has and the person's sign-in to each, as one fragment of every assistant turn.

The assistant routes from data, never from rules in its prompt (docs: assistant-routing.html): this line says which apps
are on for the team, which are installed but off, and whether this person is signed in, so the model can say "that
app is off, an admin turns it on" or expect a Connect card without a rule about any app. It is read from tools-service
(`GET /v1/apps` acting for the person, the Apps grid's own list), so an app the install lacks is never named, and only
the person's own sign-in state is shown. An app the chat left out from the composer's connector picker reads as left
out, so the model does not go looking for its tools. Kept for a short time per team and person; turning an app on
forgets the team's lines at once (team_assistant.give_app_tools).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, cast

from langgraph.config import get_config

from ops_agent_kernel.types import PromptFragment
from ops_service_kit.logging import get_logger

from ..activities.tool_directory import ToolsUnavailable
from ..domain.accounts import chosen_accounts
from ..store.team_defaults import TeamDefaults
from .child_runs import TURN_PERSON
from .deps import Runtime
from .runs import graph_store

log = get_logger("ops_agents.apps_line")

# How long one team's line for one person is kept: a sign-in made in another tab shows within this.
KEEP_S = 20.0
# The line's budget (smart-assistant.html, Context): past it the rest are counted, not named.
MAX_CHARS = 400
HEAD = "Apps for this conversation, from the team's settings:"


def describe(card: dict[str, Any]) -> str | None:
    """One app as the model reads it, or None for one it should not hear of: a built-in (its tools are offered as
    they are) or a plugin the install does not load. An app whose account this chat or its agent chose names it, so
    the model says which org it acted in; it cannot switch accounts, the person does with Change in the composer."""
    line = _describe(card)
    uses = card.get("usesAccount")
    if line is None or not uses or not line.startswith(f"{card.get('name')}: on"):
        return line
    where = f" ({card['usesAccountShown']})" if card.get("usesAccountShown") else ""
    return f"{line} · uses {uses}{where}"


def _describe(card: dict[str, Any]) -> str | None:
    kind, state, name = card.get("kind"), card.get("appState"), str(card.get("name") or "")
    if not name or kind == "builtin" or card.get("appGroup") == "gone":
        return None
    if card.get("leftOut"):
        return f"{name}: left out of this chat (the person turned it off in the composer's connectors)"
    if state == "off":
        return f"{name}: installed, off for this team (a team admin turns it on)"
    if state == "needs_auth_config":
        return f"{name}: has no auth config to sign in with (a team admin adds one)"
    if state == "auth_config_broken":
        return f"{name}: on · its auth config needs fixing (a team admin does this)"
    person = card.get("signIn") in ("person", "person_or_team")
    if state == "needs_sign_in":
        if card.get("appGroup") == "needs_you":
            return f"{name}: on · you are not signed in (a call shows a Connect card)"
        return f"{name}: on · the team account needs signing in again (a team admin does this)"
    if state == "test_failed":
        return f"{name}: on · its last sign-in test failed (a team admin checks it)"
    return f"{name}: on · " + ("you are signed in" if person else "signed in with the team account")


def left_out(
    cards: list[dict[str, Any]], held: list[str], module_of: Mapping[str, str | None], off: set[str]
) -> list[dict[str, Any]]:
    """The cards with `leftOut` on each app this chat left out: every tool the agent holds of it is in the chat's
    toolsOff (the composer's connector picker). One tool switched off in the settings panel leaves the app in."""
    out: list[dict[str, Any]] = []
    for c in cards:
        modules = set(cast(list[Any], c.get("moduleIds") or []))
        tools = {t for t in held if module_of.get(t) in modules}
        out.append({**c, "leftOut": True} if tools and tools <= off else c)
    return out


def render(cards: list[dict[str, Any]]) -> str | None:
    """The line for these cards, within MAX_CHARS; None when the team has no app to name."""
    lines = [d for c in cards if (d := describe(c)) is not None]
    if not lines:
        return None
    shown: list[str] = []
    for i, line in enumerate(lines):
        rest = len(lines) - i
        tail = f"\nand {rest} more; ask about one by name"
        if len("\n".join([HEAD, *shown, line])) + (len(tail) if rest > 1 else 0) > MAX_CHARS:
            shown.append(f"and {rest} more; ask about one by name")
            break
        shown.append(line)
    return "\n".join([HEAD, *shown])


class AppsLine:
    """graphs.common.AppsRunner: the apps line for a turn of the team's default agent with a person."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self._kept: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}

    def forget(self, team_id: str) -> None:
        """Drops the team's kept lines, so the next turn reads the apps again (an app was just turned on)."""
        for key in [k for k in self._kept if k[0] == team_id]:
            self._kept.pop(key, None)

    async def _turn(self, agent_id: str) -> tuple[str, str] | None:
        """The turn's team and person, when the turn is the team's default agent's with a person."""
        person = TURN_PERSON.get()
        if person is None or not person.email or self.rt.app_states is None:
            return None
        try:
            thread_id = str((get_config().get("configurable") or {}).get("thread_id") or "")
        except RuntimeError:
            return None  # not inside a graph run, so there is no turn
        thread = await graph_store(self.rt).thread(thread_id) if thread_id else None
        team = str(thread["team_id"]) if thread is not None else ""
        # The team's default agent only: an agent a builder made holds its own tools and needs no catalog of apps.
        if not team or await TeamDefaults(self.rt.db).agent(team) != agent_id:
            return None
        return team, person.email

    async def fragment(self, agent_id: str) -> PromptFragment | None:
        turn = await self._turn(agent_id)
        if turn is None:
            return None
        cards = await self.cards(*turn)
        if cards is None:
            return None
        text = render(await self._this_chat(agent_id, cards))
        return PromptFragment(text, False) if text else None

    async def _this_chat(self, agent_id: str, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The cards as this chat has them: an app the person left out of it reads so (left_out)."""
        try:
            thread_id = str((get_config().get("configurable") or {}).get("thread_id") or "")
        except RuntimeError:
            return cards
        thread = await graph_store(self.rt).thread(thread_id) if thread_id else None
        overrides = cast(dict[str, Any], (thread or {}).get("overrides") or {})
        off = set(cast(list[str], overrides.get("toolsOff") or []))
        agent = self.rt.catalog.agent(agent_id)
        if agent is not None:
            chosen = chosen_accounts(agent=agent.accounts, chat=cast(dict[str, str], overrides.get("accounts") or {}))
            cards = await self._uses(cards, chosen, str((thread or {}).get("team_id") or ""))
        if not off or agent is None:
            return cards
        try:
            ops = await self.rt.directory().operations()
        except ToolsUnavailable:
            return cards
        return left_out(cards, list(agent.tools), {o.name: o.module_id for o in ops}, off)

    async def _uses(self, cards: list[dict[str, Any]], chosen: dict[str, str], team: str) -> list[dict[str, Any]]:
        """The cards with the account each chosen app uses, and what it points at, from tools-service's own list."""
        if not chosen or self.rt.app_states is None:
            return cards
        out: list[dict[str, Any]] = []
        for c in cards:
            name = chosen.get(str(c.get("id")))
            if not name:
                out.append(c)
                continue
            person = TURN_PERSON.get()
            try:
                found = await self.rt.app_states.accounts(
                    person.email if person else None, team, str(c["id"]), name=name
                )
            except ToolsUnavailable:
                found = []
            # Where it points, never who signed in: the prompt must not carry a person's email.
            shown = str(found[0]["pointsAt"]) if found and found[0].get("pointsAt") else None
            out.append({**c, "usesAccount": name, **({"usesAccountShown": shown} if shown else {})})
        return out

    async def line(self, team: str, email: str, now: float | None = None) -> str | None:
        cards = await self.cards(team, email, now)
        return render(cards) if cards is not None else None

    async def cards(self, team: str, email: str, now: float | None = None) -> list[dict[str, Any]] | None:
        at = time.monotonic() if now is None else now
        kept = self._kept.get((team, email))
        if kept is not None and at - kept[0] < KEEP_S:
            return kept[1]
        assert self.rt.app_states is not None
        try:
            cards = await self.rt.app_states.cards(email, team)
        except ToolsUnavailable:
            log.info("apps_line_unavailable", team=team)
            return None
        self._kept[(team, email)] = (at, cards)
        return cards

    async def skill_needs(self, agent_id: str) -> dict[str, str]:
        agent = self.rt.catalog.agent_in_flight(agent_id)
        turn = await self._turn(agent_id)
        if agent is None or turn is None:
            return {}
        cards = await self.cards(*turn) or []
        by_module = {str(m): c for c in cards for m in cast(list[Any], c.get("moduleIds") or [])}
        try:
            ops = await self.rt.directory().operations()
        except ToolsUnavailable:
            return {}
        module_of = {o.name: o.module_id for o in ops}
        out: dict[str, str] = {}
        for s in agent.skills:
            apps = [by_module[m] for t in s.tool_ids if (m := module_of.get(t)) and m in by_module]
            if apps and (state := describe(apps[0])) is not None:
                out[s.skill_id] = "needs " + state.replace(": ", ", ", 1)
        return out
