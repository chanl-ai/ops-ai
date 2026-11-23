"""Send one message to a published agent and print the reply."""

from ops_ai import OpsAI


def main() -> None:
    ops = OpsAI()
    # Any published agent works; this path only needs a live reply.
    agent = next(row for row in ops.agents.list() if row.get("status") == "published")
    answer = ops.agents.chat(agent["id"], "What documents open a business account?")
    print(answer["reply"])


if __name__ == "__main__":
    main()
