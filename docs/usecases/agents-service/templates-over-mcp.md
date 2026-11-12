# An assistant lists and installs templates over MCP

Status: draft. Id: `uc-741`. Service: `agents-service`. Layers: mcp.

In this example we will connect an assistant to team_ops' MCP address with the official MCP SDK, find the tools
`list_templates` and `install_template`, list the starter skills, and install one as the signed-in person. It assumes
the starters pack is on for team_ops, Priya (admin) may create skills, and Maya (approver) may run tools but not
create skills.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `tools/list` as Priya | `list_templates` and `install_template` are listed |
| 2 | `list_templates {kind: skill}` | The starter skill `doc-coauthoring` is returned; the tool is marked read-only |
| 3 | `install_template` as Maya | A tool error; the team's skills are unchanged |
| 4 | `install_template` as Priya | The copy is made and is in the team's skills |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| mcp | `agents-service/scripts/test-uc-741-mcp.py` | red: the MCP address lists the team's tools only |

## Non-vacuous check

Step 3 fails if install runs as the service and not as the signed-in person.
