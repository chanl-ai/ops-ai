from ops_ai import OpsAI

ops = OpsAI()
agent = next(a for a in ops.agents.list() if a.get("status") == "published")
print(ops.agents.chat(agent["id"], "What documents open a business account?")["reply"])
