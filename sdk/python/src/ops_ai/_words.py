"""The Apps area in the words people see on screen (c-616): `apps`, `credentials`, `accounts`, `tools`, `resources` and
`usage`, each a few methods over the generated operations, which call the services' routes as they are.

An app is named by its id on the Apps page: `plugin:<plugin id>` for an app a plugin brings, `builtin:<name>` for one
of ours, or a custom app's connection id. An account is a connection id (the team account, or another named one)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

PLUGIN = "plugin:"
# Where a resource's copy is made: document types in documents-service, everything else (agents, skills, workflows)
# in agents-service.
DOCUMENT_TYPE = "document_type"


def plugin_of(app: str) -> str:
    """The plugin behind an app; only an app a plugin brings is turned on and off."""
    if not app.startswith(PLUGIN):
        raise ValueError(f"{app} is not an app a plugin brings; only those are turned on for a team")
    return app[len(PLUGIN) :]


def _connected(card: dict[str, Any]) -> bool:
    # A built-in app is always there; any other reads connected only once its team account signed in or its test
    # passed, which the card's `state` says (c-616); `status` is the account's display status.
    return card.get("kind") == "builtin" or card.get("state") == "connected"


def _environment(page: dict[str, Any], given: str | None) -> str:
    """The environment a run uses: the one given, else test when the app's account is set up for it, else production
    when that is (a plugin's app is turned on for production first). The page lists every environment, set or not."""
    if given:
        return given
    envs = cast(dict[str, dict[str, Any]], (page.get("connection") or {}).get("environments") or {})
    test, production = ((envs.get(e) or {}).get("set") for e in ("test", "production"))
    return "production" if production and not test else "test"


def _account(page: dict[str, Any]) -> str:
    connection = cast(dict[str, Any] | None, page.get("connection"))
    if not connection:
        raise ValueError(f"{page['card']['id']} has no account yet; connect it first")
    return str(connection["id"])


def _found(tool: str, modules: list[dict[str, Any]]) -> str:
    for m in modules:
        if any(o.get("name") == tool for o in m.get("operations") or []):
            return str(m["id"])
    raise ValueError(f"no tool named {tool} on this app")


def _resource(resource: dict[str, Any] | str, kind: str | None) -> tuple[str, str | None]:
    """A resource's copy route id and kind, from an item of `resources.list` or from its id."""
    if isinstance(resource, str):
        return resource, kind
    return f"{resource['source']}:{resource['id']}", str(resource.get("kind") or kind or "")


def _rows(found: Any) -> list[dict[str, Any]]:
    return list(cast(dict[str, Any], found).get("data") or []) if isinstance(found, dict) else list(found)


class Apps:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, *, connected: bool | None = None) -> list[dict[str, Any]]:
        """The Apps page's cards; `connected` keeps only the connected ones (True) or only the rest (False)."""
        cards = cast(list[dict[str, Any]], self._raw.tools.connections_list_systems())
        return [c for c in cards if connected is None or _connected(c) == connected]

    def get(self, app: str) -> dict[str, Any]:
        """One app's page: its card, account, the caller's own sign-in, tools, skills and latest calls."""
        return cast(dict[str, Any], self._raw.tools.connections_get_app(app))

    def turn_on(self, app: str, **fields: Any) -> dict[str, Any]:
        """Turns a plugin's app on for the team; `fields` are the turn-on's (accountName, credentials, signIn...)."""
        return cast(
            dict[str, Any], self._raw.tools.plugins_set_team_plugin(plugin_of(app), {"enabled": True, **fields})
        )

    def turn_off(self, app: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.plugins_set_team_plugin(plugin_of(app), {"enabled": False}))

    def users(self, app: str) -> dict[str, Any]:
        """The team's agents and workflows that use the app's tools: what turning it off stops."""
        return cast(dict[str, Any], self._raw.tools.plugins_app_users(plugin_of(app)))

    def add_custom(
        self,
        kind: str,
        name: str,
        *,
        auth_kind: str = "none",
        base_address: str,
        settings: dict[str, Any] | None = None,
        secrets: dict[str, str] | None = None,
        environment: str = "test",
    ) -> dict[str, Any]:
        """A custom app (rest, openapi or mcp): its connection, holding the base address and the key its tools use."""
        if kind == "mcp":
            return cast(dict[str, Any], self._raw.tools.connections_connect_mcp({"name": name, "url": base_address}))
        made = cast(
            dict[str, Any], self._raw.tools.connections_create_connection({"name": name, "authKind": auth_kind})
        )
        body = {
            "revision": made["revision"],
            "settings": {**(settings or {}), "baseUrl": base_address},
            "secretValues": secrets or {},
        }
        return cast(dict[str, Any], self._raw.tools.connections_set_environment(made["id"], environment, body))


class Credentials:
    """How an app signs in: Ops AI's app, or the team's own client."""

    def __init__(self, raw: Any, apps: Apps) -> None:
        self._raw, self._apps = raw, apps

    def list(self) -> list[dict[str, Any]]:
        """Each app's credential: Ops AI's app or the team's own client, its permissions, accounts and last test."""
        return cast(list[dict[str, Any]], self._raw.tools.connections_list_app_credentials())

    def create(
        self,
        app: str,
        *,
        client_id: str,
        client_secret: str,
        scopes: list[str] | None = None,
        environment: str = "production",
    ) -> dict[str, Any]:
        """Adds the team's own client to an app the team set up: its client id, secret and permissions (all when left
        out). The answer is the credential's row; it never carries the secret."""
        body: dict[str, Any] = {
            "app": app, "clientId": client_id, "clientSecret": client_secret, "environment": environment
        }  # fmt: skip
        if scopes is not None:
            body["scopes"] = scopes
        return cast(dict[str, Any], self._raw.tools.connections_create_app_credential(body))

    def set(
        self, app: str, *, client_id: str, client_secret: str | None = None, environment: str = "production"
    ) -> dict[str, Any]:
        """The team's own client on the app's account; the secret goes in once and no answer carries it."""
        account = _account(self._apps.get(app))
        detail = cast(dict[str, Any], self._raw.tools.connections_get_connection(account))
        body: dict[str, Any] = {"revision": detail["revision"], "settings": {"clientId": client_id}}
        if client_secret:
            body["secretValues"] = {"clientSecret": client_secret}
        return cast(dict[str, Any], self._raw.tools.connections_set_environment(account, environment, body))

    def test(self, app: str, *, environment: str = "production") -> dict[str, Any]:
        """Test with my account: where to send the browser; `finish` hands back what the sign-in page was given."""
        body = {"environment": environment}
        return cast(dict[str, Any], self._raw.tools.connections_check_credential(_account(self._apps.get(app)), body))

    def finish(self, app: str, *, state: str, code: str) -> dict[str, Any]:
        body = {"state": state, "code": code}
        return cast(dict[str, Any], self._raw.tools.connections_check_credential(_account(self._apps.get(app)), body))


class Accounts:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def connect(self, account: str, *, environment: str = "production", team: bool = False) -> dict[str, Any]:
        """Where to send the browser to sign in: the caller's own account, or (`team`) the team account."""
        body = {"environment": environment, "account": "team" if team else "self"}
        return cast(dict[str, Any], self._raw.tools.connections_start_sign_in(account, body))

    def test(self, account: str, *, environment: str = "production", team: bool = False) -> dict[str, Any]:
        body = {"environment": environment, "account": "team" if team else "self"}
        return cast(dict[str, Any], self._raw.tools.connections_test_connection(account, body))

    def make_default(self, account: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.connections_pin_default(account))

    def mine(self) -> list[dict[str, Any]]:
        """The caller's own accounts on every app."""
        return cast(list[dict[str, Any]], self._raw.tools.connections_my_connections())

    def set_key(self, account: str, key: str, *, environment: str = "production") -> dict[str, Any]:
        """The caller's own key on an app each person signs in to."""
        body = {"environment": environment, "credentials": {"key": key}}
        return cast(dict[str, Any], self._raw.tools.connections_give_own_credentials(account, body))

    def remove(self, account: str, *, environment: str | None = None) -> Any:
        return self._raw.tools.connections_disconnect(account, environment=environment)


class Tools:
    """An app's tools. `list` and `get` with no app keep the tool modules' listing as it was."""

    def __init__(self, raw: Any, apps: Apps, modules: Any) -> None:
        self._raw, self._apps, self._modules = raw, apps, modules

    def list(self, app: str | None = None, **query: Any) -> Iterator[Any]:
        if app is None:
            return iter(self._modules.list(**query))
        return iter(cast(list[dict[str, Any]], self._apps.get(app).get("tools") or []))

    def get(self, id: str) -> Any:
        return self._modules.get(id)

    def run(
        self,
        app: str,
        tool: str,
        input: dict[str, Any] | None = None,
        *,
        real: bool = False,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """Runs one of the app's tools: Mock reaches nothing; Real is the gateway's call, with every check."""
        page = self._apps.get(app)
        ids = [str(i) for i in page["card"].get("moduleIds") or []]
        module = ids[0] if len(ids) == 1 else _found(tool, [self._raw.tools.tool_modules_get_module(i) for i in ids])
        mode = "real" if real else "mock"
        body = {"mode": mode, "input": input or {}, "environment": _environment(page, environment)}
        return cast(dict[str, Any], self._raw.tools.tool_modules_run_tool(module, tool, body))


class Resources:
    """The agents, skills, workflows and document types an app brings, each added to the team as a copy."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, app: str | None = None) -> list[dict[str, Any]]:
        found = cast(list[dict[str, Any]], self._raw.tools.plugins_list_plugin_templates())
        return [r for r in found if app is None or r.get("source") == app]

    def add(self, resource: dict[str, Any] | str, *, kind: str | None = None, **fields: Any) -> dict[str, Any]:
        """Adds a copy to the team: an item of `list`, or its source and id (`plugin:<plugin>:<id>`) with its kind."""
        rid, kind = _resource(resource, kind)
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], service.resources_copy_resource(rid, fields))


class Usage:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, **query: Any) -> list[dict[str, Any]]:
        """This team's tool calls, newest first, each saying whom it ran as."""
        return _rows(self._raw.tools.executions_list_executions(**query))


class AsyncApps:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self, *, connected: bool | None = None) -> list[dict[str, Any]]:
        cards = cast(list[dict[str, Any]], await self._raw.tools.connections_list_systems())
        return [c for c in cards if connected is None or _connected(c) == connected]

    async def get(self, app: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.connections_get_app(app))

    async def turn_on(self, app: str, **fields: Any) -> dict[str, Any]:
        body = {"enabled": True, **fields}
        return cast(dict[str, Any], await self._raw.tools.plugins_set_team_plugin(plugin_of(app), body))

    async def turn_off(self, app: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.plugins_set_team_plugin(plugin_of(app), {"enabled": False}))

    async def users(self, app: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.plugins_app_users(plugin_of(app)))

    async def add_custom(
        self,
        kind: str,
        name: str,
        *,
        auth_kind: str = "none",
        base_address: str,
        settings: dict[str, Any] | None = None,
        secrets: dict[str, str] | None = None,
        environment: str = "test",
    ) -> dict[str, Any]:
        if kind == "mcp":
            body = {"name": name, "url": base_address}
            return cast(dict[str, Any], await self._raw.tools.connections_connect_mcp(body))
        made = cast(
            dict[str, Any], await self._raw.tools.connections_create_connection({"name": name, "authKind": auth_kind})
        )
        env = {
            "revision": made["revision"],
            "settings": {**(settings or {}), "baseUrl": base_address},
            "secretValues": secrets or {},
        }
        return cast(dict[str, Any], await self._raw.tools.connections_set_environment(made["id"], environment, env))


class AsyncCredentials:
    def __init__(self, raw: Any, apps: AsyncApps) -> None:
        self._raw, self._apps = raw, apps

    async def list(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._raw.tools.connections_list_app_credentials())

    async def set(
        self, app: str, *, client_id: str, client_secret: str | None = None, environment: str = "production"
    ) -> dict[str, Any]:
        account = _account(await self._apps.get(app))
        detail = cast(dict[str, Any], await self._raw.tools.connections_get_connection(account))
        body: dict[str, Any] = {"revision": detail["revision"], "settings": {"clientId": client_id}}
        if client_secret:
            body["secretValues"] = {"clientSecret": client_secret}
        return cast(dict[str, Any], await self._raw.tools.connections_set_environment(account, environment, body))

    async def test(self, app: str, *, environment: str = "production") -> dict[str, Any]:
        account = _account(await self._apps.get(app))
        return cast(
            dict[str, Any], await self._raw.tools.connections_check_credential(account, {"environment": environment})
        )

    async def finish(self, app: str, *, state: str, code: str) -> dict[str, Any]:
        account = _account(await self._apps.get(app))
        return cast(
            dict[str, Any], await self._raw.tools.connections_check_credential(account, {"state": state, "code": code})
        )


class AsyncAccounts:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def connect(self, account: str, *, environment: str = "production", team: bool = False) -> dict[str, Any]:
        body = {"environment": environment, "account": "team" if team else "self"}
        return cast(dict[str, Any], await self._raw.tools.connections_start_sign_in(account, body))

    async def test(self, account: str, *, environment: str = "production", team: bool = False) -> dict[str, Any]:
        body = {"environment": environment, "account": "team" if team else "self"}
        return cast(dict[str, Any], await self._raw.tools.connections_test_connection(account, body))

    async def make_default(self, account: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.connections_pin_default(account))

    async def mine(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._raw.tools.connections_my_connections())

    async def set_key(self, account: str, key: str, *, environment: str = "production") -> dict[str, Any]:
        body = {"environment": environment, "credentials": {"key": key}}
        return cast(dict[str, Any], await self._raw.tools.connections_give_own_credentials(account, body))

    async def remove(self, account: str, *, environment: str | None = None) -> Any:
        return await self._raw.tools.connections_disconnect(account, environment=environment)


class AsyncTools:
    def __init__(self, raw: Any, apps: AsyncApps, modules: Any) -> None:
        self._raw, self._apps, self._modules = raw, apps, modules

    async def list(self, app: str | None = None, **query: Any) -> list[Any]:
        if app is None:
            return [m async for m in self._modules.list(**query)]
        return list(cast(list[dict[str, Any]], (await self._apps.get(app)).get("tools") or []))

    async def get(self, id: str) -> Any:
        return await self._modules.get(id)

    async def run(
        self,
        app: str,
        tool: str,
        input: dict[str, Any] | None = None,
        *,
        real: bool = False,
        environment: str | None = None,
    ) -> dict[str, Any]:
        page = await self._apps.get(app)
        ids = [str(i) for i in page["card"].get("moduleIds") or []]
        if len(ids) == 1:
            module = ids[0]
        else:
            module = _found(tool, [await self._raw.tools.tool_modules_get_module(i) for i in ids])
        body = {
            "mode": "real" if real else "mock",
            "input": input or {},
            "environment": _environment(page, environment),
        }
        return cast(dict[str, Any], await self._raw.tools.tool_modules_run_tool(module, tool, body))


class AsyncResources:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self, app: str | None = None) -> list[dict[str, Any]]:
        found = cast(list[dict[str, Any]], await self._raw.tools.plugins_list_plugin_templates())
        return [r for r in found if app is None or r.get("source") == app]

    async def add(self, resource: dict[str, Any] | str, *, kind: str | None = None, **fields: Any) -> dict[str, Any]:
        rid, kind = _resource(resource, kind)
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], await service.resources_copy_resource(rid, fields))


class AsyncUsage:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self, **query: Any) -> list[dict[str, Any]]:
        return _rows(await self._raw.tools.executions_list_executions(**query))
