# Publish and pick a skill

**Capability id:** `skill.publish-and-pick`

Publish a skill, give it to an agent, pick it for one reply. Full Py / TS / CLI path:
[docs/guide/examples/skills.md](../../../docs/guide/examples/skills.md).

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/skills/01-publish-and-pick/setup.py
uv run pytest examples/skills/01-publish-and-pick/test_example.py
```

Happy path verbs: `ops.skills.create` / `publish`, `ops.agents.add_reference`, `ops.chat.say(..., skill=…)`.
CLI: `opsai skills apply|publish`, `opsai agents add-reference`, `opsai chat say --skill …`.

```python
skill = ops.skills.create({…})
ops.skills.publish(skill["id"], note="First version")
agent = ops.agents.apply({…})
ops.agents.add_reference(agent["id"], "skill", skill["id"])
ops.agents.publish(agent["id"], note="Uses the skill")
thread = ops.chat.start(agent["id"])
list(ops.chat.say(thread["id"], "I want to return my boots.", skill=skill["id"], inputs={"order_number": "1182"}))
```

**You should see.** A `done` message with `skills[].how == "picked"` and `order_number: 1182`. CLI grant is
`opsai agents add-reference` (skills CLI has no attach verb) — surface status **partial** for CLI grant only.
