"""A Python tool that returns the headers the system says it received, so a test sees the plugin's headers reach a
Python tool's requests, and the connection's sign-in scrubbed from the answer."""

from typing import Any

from ops_plugin_sdk import Context, tool


@tool(access="read")
def echo(ctx: Context) -> Any:
    return ctx.http.get(f"{ctx.settings.base_url}/fields/echo").json()
