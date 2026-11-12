# A team's skill is an MCP prompt

Status: draft. Id: `uc-742`. Service: `agents-service`. Layers: mcp.

In this example we will install the starter skill "Doc co-authoring" and fetch it from team_ops' MCP address as a
prompt, with its inputs as the prompt's arguments. It assumes the starters pack is on for team_ops and the skill
template declares the inputs `topic` and `doc_type`.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Install the starter skill (`install_template` shared step) | Installed |
| 2 | `prompts/list` | `doc-coauthoring` with arguments `topic` and `doc_type` |
| 3 | `prompts/get doc-coauthoring {topic: "Card dispute letters", doc_type: "runbook"}` | The skill's instructions with the topic filled in |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| mcp | `agents-service/scripts/test-uc-742-mcp.py` | red: skills have no inputs and the MCP address offers no prompts |

## Non-vacuous check

Step 2 fails while a skill keeps no inputs; step 3 fails if the arguments are not substituted.
