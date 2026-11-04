"""The Apps area in the words people see on screen: `apps`, `credentials`, `accounts`, `tools`, `resources` and
`usage`, each a few methods over the generated operations, which call the services' routes as they are.

An app is named by its id on the Apps page: `plugin:<plugin id>` for an app a plugin brings, `builtin:<name>` for one
of ours, or a custom app's id. An app's accounts are the team account and any other named one, a sandbox among them (the
account a test run uses); an account method left without `account` acts on the app's default account."""

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
    # passed, which the card's `state` says; `status` is the account's display status.
    return card.get("kind") == "builtin" or card.get("state") == "connected"


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


def _keys(
    made: dict[str, Any], base_address: str, settings: dict[str, Any] | None, secrets: dict[str, str] | None
) -> dict[str, Any]:
    """The first account's settings: the base address its tools call, and the key they send."""
    return {
        "revision": made["revision"],
        "settings": {**(settings or {}), "baseUrl": base_address},
        "secretValues": secrets or {},
    }


class Apps:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, *, connected: bool | None = None) -> list[dict[str, Any]]:
        """The Apps page's cards; `connected` keeps only the connected ones (True) or only the rest (False)."""
        cards = cast(list[dict[str, Any]], self._raw.tools.apps_list_apps())
        return [c for c in cards if connected is None or _connected(c) == connected]

    def get(self, app: str) -> dict[str, Any]:
        """One app's page: its card, accounts, the caller's own sign-in, tools, skills and latest calls."""
        return cast(dict[str, Any], self._raw.tools.apps_get_app(app))

    def turn_on(self, app: str, **fields: Any) -> dict[str, Any]:
        """Turns a plugin's app on for the team; `fields` are the turn-on's (accountName, credentialId, credentials,
        signIn...). Leaving credentialId out signs in with Ops AI's app."""
        plugin_of(app)
        return cast(dict[str, Any], self._raw.tools.apps_set_team_app(app, {"enabled": True, **fields}))

    def turn_off(self, app: str) -> dict[str, Any]:
        plugin_of(app)
        return cast(dict[str, Any], self._raw.tools.apps_set_team_app(app, {"enabled": False}))

    def users(self, app: str) -> dict[str, Any]:
        """The team's agents and workflows that use the app's tools: what turning it off stops."""
        plugin_of(app)
        return cast(dict[str, Any], self._raw.tools.apps_app_users(app))

    def add_custom(
        self,
        kind: str,
        name: str,
        *,
        auth_kind: str = "none",
        base_address: str,
        settings: dict[str, Any] | None = None,
        secrets: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """A custom app (rest, openapi or mcp) as its first account, holding the base address and the key its tools
        use."""
        if kind == "mcp":
            return cast(dict[str, Any], self._raw.tools.apps_add_app({"name": name, "serverUrl": base_address}))
        made = cast(dict[str, Any], self._raw.tools.apps_add_app({"name": name, "authKind": auth_kind}))
        body = _keys(made, base_address, settings, secrets)
        return cast(dict[str, Any], self._raw.tools.apps_change_account(made["id"], made["id"], body))


class Credentials:
    """How an app signs in: Ops AI's app, or one of the team's own clients (app credentials)."""

    def __init__(self, raw: Any, apps: Apps) -> None:
        self._raw, self._apps = raw, apps

    def list(self) -> list[dict[str, Any]]:
        """The team's app credentials and Ops AI's app of each app using it: permissions, accounts and last test."""
        return cast(list[dict[str, Any]], self._raw.tools.apps_list_app_credentials())

    def get(self, credential: str) -> dict[str, Any]:
        """One app credential with the accounts signing in with it."""
        return cast(dict[str, Any], self._raw.tools.apps_get_app_credential(credential))

    def create(
        self,
        app: str,
        *,
        client_id: str,
        client_secret: str | None = None,
        name: str | None = None,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """The team's own client for an app: its client id, secret (none for a public client or one that signs an
        assertion) and permissions (all when left out), with no account needed. Accounts pick it by its id (`set`, or
        credentialId when connected); no answer carries the secret."""
        body: dict[str, Any] = {"app": app, "clientId": client_id}
        if client_secret is not None:
            body["clientSecret"] = client_secret
        if name is not None:
            body["name"] = name
        if scopes is not None:
            body["scopes"] = scopes
        return cast(dict[str, Any], self._raw.tools.apps_create_app_credential(body))

    def replace_secret(self, credential: str, client_secret: str) -> dict[str, Any]:
        """A new client secret for the team's own client; every account on it keeps it."""
        body = {"clientSecret": client_secret}
        return cast(dict[str, Any], self._raw.tools.apps_set_app_credential_secret(credential, body))

    def set(self, app: str, credential: str | None, *, account: str | None = None) -> dict[str, Any]:
        """Signs the app's account (its default unless `account`) in with one of the team's credentials, or with None,
        Ops AI's app. The account signs in again."""
        account = account or _account(self._apps.get(app))
        detail = cast(dict[str, Any], self._raw.tools.apps_get_account(app, account))
        body: dict[str, Any] = {"revision": detail["revision"], "credentialId": credential}
        return cast(dict[str, Any], self._raw.tools.apps_change_account(app, account, body))

    def test(self, app: str, *, account: str | None = None) -> dict[str, Any]:
        """Test with my account: where to send the browser; `finish` hands back what the sign-in page was given."""
        account = account or _account(self._apps.get(app))
        return cast(dict[str, Any], self._raw.tools.apps_check_credential(app, account, {}))

    def finish(self, app: str, *, state: str, code: str, account: str | None = None) -> dict[str, Any]:
        account = account or _account(self._apps.get(app))
        body = {"state": state, "code": code}
        return cast(dict[str, Any], self._raw.tools.apps_check_credential(app, account, body))


class Accounts:
    def __init__(self, raw: Any, apps: Apps) -> None:
        self._raw, self._apps = raw, apps

    def _default(self, app: str, account: str | None) -> str:
        return account or _account(self._apps.get(app))

    def add(self, app: str, name: str, *, sandbox: bool = False, **fields: Any) -> dict[str, Any]:
        """Another account of an app the team has: a sandbox, which test runs use, or another named one; `fields` are
        a plugin account's turn-on fields (credentialId, credentials, signIn...)."""
        body = {"name": name, "sandbox": sandbox, **fields}
        return cast(dict[str, Any], self._raw.tools.apps_add_account(app, body))

    def connect(self, app: str, *, account: str | None = None, team: bool = False) -> dict[str, Any]:
        """Where to send the browser to sign in: the caller's own account, or (`team`) the team account."""
        body = {"account": "team" if team else "self"}
        return cast(dict[str, Any], self._raw.tools.apps_start_sign_in(app, self._default(app, account), body))

    def test(self, app: str, *, account: str | None = None, team: bool = False) -> dict[str, Any]:
        body = {"account": "team" if team else "self"}
        return cast(dict[str, Any], self._raw.tools.apps_test_account(app, self._default(app, account), body))

    def make_default(self, app: str, account: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.apps_pin_default(app, account))

    def mine(self) -> list[dict[str, Any]]:
        """The caller's own accounts on every app."""
        return cast(list[dict[str, Any]], self._raw.tools.apps_my_accounts())

    def set_key(self, account: str, key: str) -> dict[str, Any]:
        """The caller's own key on an account each person signs in to."""
        body = {"credentials": {"key": key}}
        return cast(dict[str, Any], self._raw.tools.apps_give_own_credentials(account, body))

    def remove(self, account: str) -> Any:
        return self._raw.tools.apps_disconnect(account)


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
        body: dict[str, Any] = {"mode": "real" if real else "mock", "input": input or {}}
        if environment is not None:
            # Left out, a Real run is a test run: the app's sandbox account when it has one.
            body["environment"] = environment
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
        cards = cast(list[dict[str, Any]], await self._raw.tools.apps_list_apps())
        return [c for c in cards if connected is None or _connected(c) == connected]

    async def get(self, app: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.apps_get_app(app))

    async def turn_on(self, app: str, **fields: Any) -> dict[str, Any]:
        plugin_of(app)
        return cast(dict[str, Any], await self._raw.tools.apps_set_team_app(app, {"enabled": True, **fields}))

    async def turn_off(self, app: str) -> dict[str, Any]:
        plugin_of(app)
        return cast(dict[str, Any], await self._raw.tools.apps_set_team_app(app, {"enabled": False}))

    async def users(self, app: str) -> dict[str, Any]:
        plugin_of(app)
        return cast(dict[str, Any], await self._raw.tools.apps_app_users(app))

    async def add_custom(
        self,
        kind: str,
        name: str,
        *,
        auth_kind: str = "none",
        base_address: str,
        settings: dict[str, Any] | None = None,
        secrets: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if kind == "mcp":
            return cast(dict[str, Any], await self._raw.tools.apps_add_app({"name": name, "serverUrl": base_address}))
        made = cast(dict[str, Any], await self._raw.tools.apps_add_app({"name": name, "authKind": auth_kind}))
        body = _keys(made, base_address, settings, secrets)
        return cast(dict[str, Any], await self._raw.tools.apps_change_account(made["id"], made["id"], body))


class AsyncCredentials:
    def __init__(self, raw: Any, apps: AsyncApps) -> None:
        self._raw, self._apps = raw, apps

    async def list(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._raw.tools.apps_list_app_credentials())

    async def get(self, credential: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.apps_get_app_credential(credential))

    async def create(
        self,
        app: str,
        *,
        client_id: str,
        client_secret: str | None = None,
        name: str | None = None,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"app": app, "clientId": client_id}
        if client_secret is not None:
            body["clientSecret"] = client_secret
        if name is not None:
            body["name"] = name
        if scopes is not None:
            body["scopes"] = scopes
        return cast(dict[str, Any], await self._raw.tools.apps_create_app_credential(body))

    async def replace_secret(self, credential: str, client_secret: str) -> dict[str, Any]:
        body = {"clientSecret": client_secret}
        return cast(dict[str, Any], await self._raw.tools.apps_set_app_credential_secret(credential, body))

    async def set(self, app: str, credential: str | None, *, account: str | None = None) -> dict[str, Any]:
        account = account or _account(await self._apps.get(app))
        detail = cast(dict[str, Any], await self._raw.tools.apps_get_account(app, account))
        body: dict[str, Any] = {"revision": detail["revision"], "credentialId": credential}
        return cast(dict[str, Any], await self._raw.tools.apps_change_account(app, account, body))

    async def test(self, app: str, *, account: str | None = None) -> dict[str, Any]:
        account = account or _account(await self._apps.get(app))
        return cast(dict[str, Any], await self._raw.tools.apps_check_credential(app, account, {}))

    async def finish(self, app: str, *, state: str, code: str, account: str | None = None) -> dict[str, Any]:
        account = account or _account(await self._apps.get(app))
        body = {"state": state, "code": code}
        return cast(dict[str, Any], await self._raw.tools.apps_check_credential(app, account, body))


class AsyncAccounts:
    def __init__(self, raw: Any, apps: AsyncApps) -> None:
        self._raw, self._apps = raw, apps

    async def _default(self, app: str, account: str | None) -> str:
        return account or _account(await self._apps.get(app))

    async def add(self, app: str, name: str, *, sandbox: bool = False, **fields: Any) -> dict[str, Any]:
        body = {"name": name, "sandbox": sandbox, **fields}
        return cast(dict[str, Any], await self._raw.tools.apps_add_account(app, body))

    async def connect(self, app: str, *, account: str | None = None, team: bool = False) -> dict[str, Any]:
        body = {"account": "team" if team else "self"}
        found = await self._default(app, account)
        return cast(dict[str, Any], await self._raw.tools.apps_start_sign_in(app, found, body))

    async def test(self, app: str, *, account: str | None = None, team: bool = False) -> dict[str, Any]:
        body = {"account": "team" if team else "self"}
        found = await self._default(app, account)
        return cast(dict[str, Any], await self._raw.tools.apps_test_account(app, found, body))

    async def make_default(self, app: str, account: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.apps_pin_default(app, account))

    async def mine(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._raw.tools.apps_my_accounts())

    async def set_key(self, account: str, key: str) -> dict[str, Any]:
        body = {"credentials": {"key": key}}
        return cast(dict[str, Any], await self._raw.tools.apps_give_own_credentials(account, body))

    async def remove(self, account: str) -> Any:
        return await self._raw.tools.apps_disconnect(account)


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
        body: dict[str, Any] = {"mode": "real" if real else "mock", "input": input or {}}
        if environment is not None:
            body["environment"] = environment
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
