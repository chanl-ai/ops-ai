"""Send one message to a published agent and print the reply."""

from __future__ import annotations

from typing import TypedDict, cast

from ops_ai import OpsAI


class AgentRow(TypedDict):
    id: str
    status: str


class ChatReply(TypedDict):
    reply: str
    threadId: str


def main() -> None:
    ops = OpsAI()
    agent = cast(
        AgentRow,
        next(row for row in ops.agents.list() if row.get("status") == "published"),
    )
    answer = cast(
        ChatReply,
        ops.agents.chat(agent["id"], "What documents open a business account?"),
    )
    print(answer["reply"])


if __name__ == "__main__":
    main()
