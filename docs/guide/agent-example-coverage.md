# Agent example coverage

Status: current. Generated from the Example folders by the repository checker.

| Example | Outcome | Status | Capabilities |
|---|---|---|---|
| `answer-from-instructions` | Ask a published agent one question and read the reply. | Built | agent.instructions, agent.chat |
| `cite-the-handbook` | Ask a question the handbook page answers and see the cited section. | Built | agent.knowledge |
| `look-up-a-customer` | Ask for a customer; the agent calls the read tool. | Built | agent.tool.read |
| `draft-a-note-for-approval` | Draft a customer note that waits for approval before writing. | Built | agent.tool.write |
| `follow-a-checklist` | Follow a reusable checklist and block investment advice. | Built | agent.skills, agent.guardrails |
| `narrow-one-conversation` | Narrow one conversation to a model, knowledge and tool subset. | Built | agent.overrides |
| `start-customer-hold` | Specialist chat starts the hold workflow as a governed tool. | Built | agent.workflow-tool |
| `run-in-three-modes` | Start one agent in stream, wait and background modes. | Built | agent.run-api |
| `delegate-to-a-specialist` | A triage agent delegates research to a specialist. | Built | agent.delegate |
| `morning-held-wires` | A scheduled agent job returns a report. | Built | agent.jobs |
| `eval-a-known-customer` | Score A3 look-up cases on a published agent through ops.agents.eval. | Built | agent.eval |
