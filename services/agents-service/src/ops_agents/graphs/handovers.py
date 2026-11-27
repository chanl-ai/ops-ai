"""Hand-overs for the `swarm` loop kind, carried out by the runtime
(docs/design/agents-v2/automatic-mode-and-loop-kinds.md, "Hand-overs"). The `hand_over` tool only records where the
conversation goes; once the turn ends, `run_with_handovers` starts the receiving agent's own turn from the
conversation's shared notes and the hand-over message, never from the previous agent's exchange. Each turn is an
ordinary turn, so pause, resume, budget and trace need nothing new.

Rules: at most `max_handoffs` per turn of the person; an agent cannot hand to itself, nor back to an agent that already
had this turn of the person.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ops_agent_kernel.ports import ToolExecutor, ToolOutcome
from ops_agent_kernel.types import ToolGrant, TurnResult
from ops_service_kit.http import Json

HAND_OVER = "hand_over"
ADD_NOTE = "add_note"
SERVER = "handovers"
NOTE_CHARS = 500


def refused_at(limit: int) -> str:
    return f"The conversation was handed over {limit} times on this message; answer the person yourself."


def grants(targets: dict[str, str]) -> list[ToolGrant]:
    """The hand-over and note tools for a swarm turn; `targets` maps each agent it may hand to onto its name."""
    names = "; ".join(f"{aid} ({name})" for aid, name in targets.items())
    return [
        ToolGrant(
            HAND_OVER,
            SERVER,
            f"Hand the conversation to another agent when it should answer this, with a short message saying what the "
            f"person needs. Write down what it must know with add_note first. Agents: {names}.",
            "read",
            {
                "type": "object",
                "properties": {
                    "agentId": {"type": "string", "enum": list(targets)},
                    "message": {"type": "string", "maxLength": 1000},
                },
                "required": ["agentId", "message"],
            },
        ),
        ToolGrant(
            ADD_NOTE,
            SERVER,
            "Keep a fact for every agent of this conversation, such as a customer id or what the person already said.",
            "read",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
    ]


@dataclass
class Handovers:
    """One turn of the person: how many hand-overs it made, the agents that had it, and the notes they share."""

    max_handoffs: int
    notes: list[str] = field(default_factory=list[str])
    count: int = 0
    had: list[str] = field(default_factory=list[str])
    # Set by the hand_over tool during a turn: the agent asked for and the message it starts from.
    asked: tuple[str, str] | None = None


@dataclass
class HandoverTools:
    """The kernel's tool port with the hand-over and note tools answered here; every other tool goes to `inner`."""

    inner: ToolExecutor
    turn: Handovers
    me: str
    targets: frozenset[str]

    async def execute(self, tool: str, arguments: Json, *, key: str, approval_token: str | None) -> ToolOutcome:
        if tool == ADD_NOTE:
            text = str(arguments.get("text") or "").strip()[:NOTE_CHARS]
            if text:
                self.turn.notes.append(text)
            return ToolOutcome(True, {"ok": True})
        if tool != HAND_OVER:
            return await self.inner.execute(tool, arguments, key=key, approval_token=approval_token)
        to = str(arguments.get("agentId") or "")
        if self.turn.count >= self.turn.max_handoffs:
            return ToolOutcome(False, {"error": refused_at(self.turn.max_handoffs)})
        if to == self.me or to not in self.targets:
            return ToolOutcome(False, {"error": f"You cannot hand over to {to or 'nobody'}; pick one of the agents."})
        if to in self.turn.had:
            return ToolOutcome(False, {"error": "That agent already had this message; answer the person yourself."})
        self.turn.asked = (to, str(arguments.get("message") or ""))
        return ToolOutcome(True, {"status": "handed_over", "next": "Tell the person in one line who takes over."})


def opening(notes: list[str], message: str) -> str:
    """What the receiving agent's turn starts from: the shared notes and the hand-over message."""
    lines = "\n".join(f"- {n}" for n in notes)
    said = f"## Notes for this conversation\n\n{lines}\n\n" if notes else ""
    return f"{said}## Handed to you\n\n{message}"


Turn = Callable[[str, str, Handovers], Awaitable[TurnResult]]


async def run_with_handovers(first: str, message: str, turn: Turn, h: Handovers) -> list[tuple[str, TurnResult]]:
    """Runs `first`'s turn on `message`, then each agent it is handed to, until one answers, pauses or fails. Each pair
    is an agent and its turn, in order; the last is the reply the person reads."""
    current, said = first, message
    out: list[tuple[str, TurnResult]] = []
    while True:
        h.asked = None
        h.had.append(current)
        result = await turn(current, said, h)
        out.append((current, result))
        # Read once the turn is over: the hand_over tool set it while the turn ran.
        asked: tuple[str, str] | None = getattr(h, "asked")  # noqa: B009
        if asked is None or result.status != "completed":
            return out
        to, msg = asked
        h.count += 1
        current, said = to, opening(h.notes, msg)
