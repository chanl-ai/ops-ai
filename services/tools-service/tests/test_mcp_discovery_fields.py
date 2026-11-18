from ops_service_kit.http import Json
from ops_service_kit.narrow import json_list, json_object
from ops_tools.mcp import discovered


def test_one_tool_with_a_nullable_type_and_a_numeric_enum_does_not_stop_discovery() -> None:
    """Real MCP servers declare `type: ["string", "null"]` and numeric enums; discovery lists every tool as given and
    only saving that field is checked."""
    tools: list[Json] = [
        {
            "name": "set_level",
            "inputSchema": {
                "type": "object",
                "properties": {"note": {"type": ["string", "null"]}, "a": {"type": "integer", "enum": [1, 2]}},
                "required": "a",
            },
        }
    ]
    found = discovered(tools, "https://mcp.example.test", {})
    assert json_object(json_list(found["operations"])[0])["input"] == [
        {"name": "note", "type": ["string", "null"], "required": False},
        {"name": "a", "type": "integer", "required": True, "enum": [1, 2]},
    ]
