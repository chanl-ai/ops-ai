"""A Python tool that returns what the system says it was sent, credential included: the plugin executor must scrub
the connection's sign-in from a Python tool's answer as the http executor does (c-588)."""

from typing import Any

from ops_plugin_sdk import Context, tool


@tool(access="read")
def echo(ctx: Context) -> Any:
    return ctx.http.get(f"{ctx.settings.base_url}/bearer/echo").json()
