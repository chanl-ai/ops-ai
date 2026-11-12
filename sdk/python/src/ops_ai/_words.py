"""The Apps area in the words people see on screen: `apps`, `credentials`, `accounts`, `tools`, `resources`,
`usage` and `me.connectors` (Connectors (Mine)), each a few methods over the generated operations, which call the
services' routes as they are.

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
    # Connected is the card's appGroup `on`: the app works for the caller (tools-service decides it).
    return card.get("kind") == "builtin" or card.get("appGroup") == "on"


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


def _copy(made: dict[str, Any]) -> tuple[str, str, str]:
    """A copy's kind, record id and resource id, from an answer of `add`, a row of `list`, or the copy itself."""
    c = cast(dict[str, Any], made.get("copy") if isinstance(made.get("copy"), dict) else made)
    if not c.get("recordId"):
        raise ValueError("no copy here: add the resource to the team first")
    return str(c["kind"]), str(c["recordId"]), f"{c['source']}:{c['templateId']}"


# The delete each kind's copy goes through, by the service that keeps it.
_DELETES = {
    "agent": ("agents", "agents_delete_agent"),
    "skill": ("agents", "agents_delete_skill"),
    "workflow": ("agents", "workflows_delete_definition"),
    DOCUMENT_TYPE: ("documents", "document_types_delete_type"),
    "knowledge_source": ("kb", "sources_remove_source"),
}


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


def _picked(found: dict[str, Any], names: list[str] | None) -> list[dict[str, Any]]:
    """The discovered operations to import: the named ones, or all; a name the document lacks is refused rather than
    skipped, because a typo would import less than the builder ticked."""
    ops = list(found.get("operations") or [])
    if names is None:
        return ops
    missing = [n for n in names if not any(o.get("name") == n for o in ops)]
    if missing:
        raise ValueError(f"the document has no operation named {', '.join(missing)}")
    return [o for o in ops if o.get("name") in names]


def _waiting_review(module: dict[str, Any]) -> str:
    """The id of the security review a module's version waits on."""
    for v in module.get("versions") or []:
        if v.get("status") == "in_review" and v.get("reviewId"):
            return str(v["reviewId"])
    raise ValueError("this tool module has no version waiting on a security review; request one first")


def _source(spec_url: str, connection_id: str | None) -> dict[str, Any]:
    return {"kind": "openapi", "specUrl": spec_url, **({"connectionId": connection_id} if connection_id else {})}


class Secrets:
    """The team's secrets (Settings > Secrets). A value goes in and is never read back: no answer carries it."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self) -> list[dict[str, Any]]:
        return _rows(self._raw.tools.secrets_list_secrets())

    def create(self, name: str, value: str, *, teams: list[str] | None = None) -> dict[str, Any]:
        """Stores a secret as the team's; `teams` also shares it with other teams of the caller."""
        body: dict[str, Any] = {"name": name, "value": value, **({"teams": teams} if teams else {})}
        return cast(dict[str, Any], self._raw.tools.secrets_create_secret(body))

    def rotate(self, name: str, value: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.secrets_rotate_secret(name, {"value": value}))

    def rename(self, name: str, new_name: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.secrets_rename_secret(name, {"name": new_name}))

    def delete(self, name: str) -> Any:
        return self._raw.tools.secrets_delete_secret(name)


class Egress:
    """The hosts and address ranges tools may reach (Settings > Egress); only a Security admin changes them."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.egress_allow_list())

    def allow_host(self, host: str, note: str = "") -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.egress_add_host({"value": host, "note": note}))

    def allow_range(self, cidr: str, note: str = "") -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.egress_add_range({"value": cidr, "note": note}))

    def remove_host(self, host: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.egress_remove_host({"value": host}))

    def remove_range(self, cidr: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.egress_remove_range({"value": cidr}))


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

    def give_assistant(self, app: str) -> dict[str, Any]:
        """Gives the team's assistant the app's read tools the team added (the Turn on window's choice): which tools,
        and whether it was published at once (given), waits on a review, or waits on someone's draft."""
        modules = list(self.get(app)["card"].get("moduleIds") or [])
        return cast(dict[str, Any], self._raw.agents.agents_give_assistant_app_tools({"moduleIds": modules}))

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


class Connectors:
    """The caller's connectors, as Connectors (Mine) lists them: one row per app that acts as them."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self) -> list[dict[str, Any]]:
        """One row per app: what it can do as the caller, whom it signs in as, its app's state for them (appState,
        as GET /v1/apps answers it) and who acts next (appGroup), and its accounts as a count with a primary."""
        return cast(list[dict[str, Any]], self._raw.tools.apps_my_connections())

    def get(self, app: str) -> dict[str, Any]:
        found = next((c for c in self.list() if c["appId"] == app or str(c["name"]).lower() == app.lower()), None)
        if found is None:
            raise ValueError(f"{app} is not one of your connectors")
        return found

    def disconnect(self, app: str, *, account: str | None = None) -> None:
        """Ends the caller's own sign-in on the app's primary account, or on `account`."""
        connector = self.get(app)
        target = account or connector.get("primaryAccountId")
        if not target:
            raise ValueError(f"{connector['name']} has no account of yours to disconnect")
        self._raw.tools.apps_disconnect(target)

    def connect(
        self, app: str | None = None, *, link: str | None = None, account: str | None = None, team: bool = False
    ) -> dict[str, Any]:
        """Starts a sign-in and returns where to send the browser (`authorizeUrl`). Pass `link`, the connect link a
        call for the caller was answered with, or `app` to sign in from the connector itself."""
        if link:
            return cast(dict[str, Any], self._raw.tools.apps_open_connect_link({"link": link}))
        if not app:
            raise ValueError("connect needs an app or a connect link")
        connector = self.get(app)
        target = account or connector.get("primaryAccountId") or connector["appId"]
        body = {"account": "team" if team else "self"}
        return cast(dict[str, Any], self._raw.tools.apps_start_sign_in(connector["appId"], target, body))

    def finish(self, state: str, code: str | None = None, *, error: str | None = None) -> dict[str, Any]:
        """Finishes the sign-in the browser came back from, with the `state` and `code` of its return address."""
        body = {k: v for k, v in {"state": state, "code": code, "error": error}.items() if v is not None}
        return cast(dict[str, Any], self._raw.tools.apps_finish_sign_in(body))

    def accounts(self) -> list[dict[str, Any]]:
        """The caller's own accounts on every app."""
        return cast(list[dict[str, Any]], self._raw.tools.apps_my_accounts())


class Me:
    """What belongs to the caller themselves."""

    def __init__(self, raw: Any) -> None:
        self.connectors = Connectors(raw)


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

    def create_module(self, name: str, display_name: str, *, type: str = "openapi") -> dict[str, Any]:
        """An empty tool module for the team's builders to import operations into."""
        body = {"name": name, "displayName": display_name, "type": type}
        return cast(dict[str, Any], self._raw.tools.tool_modules_create_blank_module(body))

    def discover(self, spec_url: str, *, connection_id: str | None = None) -> dict[str, Any]:
        """Reads an OpenAPI document and lists the operations it would bring, each with the access the method gives
        it (GET is read, the rest write). Nothing is saved."""
        return cast(dict[str, Any], self._raw.tools.tool_modules_discover(_source(spec_url, connection_id)))

    def import_openapi(
        self, module: str, spec_url: str, operations: list[str] | None = None, *, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Imports the ticked operations (all when `operations` is left out) of an OpenAPI document into a module's
        draft; it is published by a security review and `publish_version`."""
        source = _source(spec_url, connection_id)
        found = cast(dict[str, Any], self._raw.tools.tool_modules_discover(source))
        body = {"source": source, "operations": _picked(found, operations)}
        return cast(dict[str, Any], self._raw.tools.tool_modules_import_operations(module, body))

    def request_review(self, module: str, note: str = "") -> dict[str, Any]:
        """Asks the Security team to review the module's draft."""
        return cast(dict[str, Any], self._raw.tools.tool_modules_request_review(module, {"note": note}))

    def review_of(self, module: dict[str, Any]) -> str:
        """The id of the security review a module detail (from `request_review` or `get`) waits on. Security does not
        see the owner's module, so the owner passes this id on."""
        return _waiting_review(module)

    def decide_review(self, review: str, decision: str = "approved", *, reason: str | None = None) -> dict[str, Any]:
        """The Security team's answer to a module's review; `approved` publishes the module."""
        body = {"decision": decision, **({"reason": reason} if reason else {})}
        return cast(dict[str, Any], self._raw.agents.reviews_decide_publish_request(review, body))

    def publish_version(self, module: str, note: str = "") -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.tools.tool_modules_publish_version(module, {"note": note}))

    def run_module(
        self,
        module: str,
        tool: str,
        input: dict[str, Any] | None = None,
        *,
        real: bool = False,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """`run` for a module that is not an app: the test panel's call on the module itself."""
        body: dict[str, Any] = {"mode": "real" if real else "mock", "input": input or {}}
        if environment is not None:
            body["environment"] = environment
        return cast(dict[str, Any], self._raw.tools.tool_modules_run_tool(module, tool, body))


class Resources:
    """The agents, skills, workflows and document types an app brings, each added to the team as a copy."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, app: str) -> list[dict[str, Any]]:
        """The app's resources as its Resources tab shows them: each with its state for the team, the team's copy, and
        whether you may add it (`canAdd`, with `reason` naming who can when you cannot)."""
        return cast(list[dict[str, Any]], self._raw.tools.plugins_list_app_resources(app))

    def plan(self, resources: list[dict[str, Any] | str]) -> dict[str, Any]:
        """The preview of adding several: each resource, each one it brings with it, the copies the team already holds,
        the bindings to fill and anything refused, in the order the adds run. Nothing is made."""
        ids = [_resource(r, None)[0] for r in resources]
        return cast(dict[str, Any], self._raw.agents.resources_plan_resources({"resources": ids}))

    def add(self, resource: dict[str, Any] | str, *, kind: str | None = None, **fields: Any) -> dict[str, Any]:
        """Adds a copy to the team: an item of `list`, or its source and id (`plugin:<plugin>:<id>`) with its kind."""
        rid, kind = _resource(resource, kind)
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], service.resources_copy_resource(rid, fields))

    def update(self, copy: dict[str, Any], *, confirm: bool = False) -> dict[str, Any]:
        """Takes the app's current template as a new draft version of the copy (an answer of `add` or a row of `list`).
        A copy the team edited since is refused (409 copy_edited, listing the edits) until `confirm` is True."""
        kind, record, rid = _copy(copy)
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], service.resources_take_update(rid, record, {"confirm": confirm}))

    def remove(self, copy: dict[str, Any]) -> None:
        """Deletes the team's copy through its kind's own delete, which refuses (409 in_use) while others use it."""
        kind, record, _ = _copy(copy)
        service, op = _DELETES[kind]
        getattr(getattr(self._raw, service), op)(record)


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

    async def give_assistant(self, app: str) -> dict[str, Any]:
        modules = list((await self.get(app))["card"].get("moduleIds") or [])
        return cast(dict[str, Any], await self._raw.agents.agents_give_assistant_app_tools({"moduleIds": modules}))

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


class AsyncConnectors:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._raw.tools.apps_my_connections())

    async def get(self, app: str) -> dict[str, Any]:
        rows = await self.list()
        found = next((c for c in rows if c["appId"] == app or str(c["name"]).lower() == app.lower()), None)
        if found is None:
            raise ValueError(f"{app} is not one of your connectors")
        return found

    async def disconnect(self, app: str, *, account: str | None = None) -> None:
        connector = await self.get(app)
        target = account or connector.get("primaryAccountId")
        if not target:
            raise ValueError(f"{connector['name']} has no account of yours to disconnect")
        await self._raw.tools.apps_disconnect(target)

    async def connect(
        self, app: str | None = None, *, link: str | None = None, account: str | None = None, team: bool = False
    ) -> dict[str, Any]:
        """Starts a sign-in and returns where to send the browser (`authorizeUrl`). Pass `link`, the connect link a
        call for the caller was answered with, or `app` to sign in from the connector itself."""
        if link:
            return cast(dict[str, Any], await self._raw.tools.apps_open_connect_link({"link": link}))
        if not app:
            raise ValueError("connect needs an app or a connect link")
        connector = await self.get(app)
        target = account or connector.get("primaryAccountId") or connector["appId"]
        body = {"account": "team" if team else "self"}
        return cast(dict[str, Any], await self._raw.tools.apps_start_sign_in(connector["appId"], target, body))

    async def finish(self, state: str, code: str | None = None, *, error: str | None = None) -> dict[str, Any]:
        """Finishes the sign-in the browser came back from, with the `state` and `code` of its return address."""
        body = {k: v for k, v in {"state": state, "code": code, "error": error}.items() if v is not None}
        return cast(dict[str, Any], await self._raw.tools.apps_finish_sign_in(body))

    async def accounts(self) -> list[dict[str, Any]]:
        """The caller's own accounts on every app."""
        return cast(list[dict[str, Any]], await self._raw.tools.apps_my_accounts())


class AsyncMe:
    def __init__(self, raw: Any) -> None:
        self.connectors = AsyncConnectors(raw)


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

    async def create_module(self, name: str, display_name: str, *, type: str = "openapi") -> dict[str, Any]:
        """An empty tool module for the team's builders to import operations into."""
        body = {"name": name, "displayName": display_name, "type": type}
        return cast(dict[str, Any], await self._raw.tools.tool_modules_create_blank_module(body))

    async def discover(self, spec_url: str, *, connection_id: str | None = None) -> dict[str, Any]:
        """Reads an OpenAPI document and lists the operations it would bring, each with the access the method gives
        it (GET is read, the rest write). Nothing is saved."""
        return cast(dict[str, Any], await self._raw.tools.tool_modules_discover(_source(spec_url, connection_id)))

    async def import_openapi(
        self, module: str, spec_url: str, operations: list[str] | None = None, *, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Imports the ticked operations (all when `operations` is left out) of an OpenAPI document into a module's
        draft; it is published by a security review and `publish_version`."""
        source = _source(spec_url, connection_id)
        found = cast(dict[str, Any], await self._raw.tools.tool_modules_discover(source))
        body = {"source": source, "operations": _picked(found, operations)}
        return cast(dict[str, Any], await self._raw.tools.tool_modules_import_operations(module, body))

    async def request_review(self, module: str, note: str = "") -> dict[str, Any]:
        """Asks the Security team to review the module's draft."""
        return cast(dict[str, Any], await self._raw.tools.tool_modules_request_review(module, {"note": note}))

    def review_of(self, module: dict[str, Any]) -> str:
        return _waiting_review(module)

    async def decide_review(
        self, review: str, decision: str = "approved", *, reason: str | None = None
    ) -> dict[str, Any]:
        body = {"decision": decision, **({"reason": reason} if reason else {})}
        return cast(dict[str, Any], await self._raw.agents.reviews_decide_publish_request(review, body))

    async def publish_version(self, module: str, note: str = "") -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.tool_modules_publish_version(module, {"note": note}))

    async def run_module(
        self,
        module: str,
        tool: str,
        input: dict[str, Any] | None = None,
        *,
        real: bool = False,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """`run` for a module that is not an app: the test panel's call on the module itself."""
        body: dict[str, Any] = {"mode": "real" if real else "mock", "input": input or {}}
        if environment is not None:
            body["environment"] = environment
        return cast(dict[str, Any], await self._raw.tools.tool_modules_run_tool(module, tool, body))


class AsyncResources:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self, app: str) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._raw.tools.plugins_list_app_resources(app))

    async def plan(self, resources: list[dict[str, Any] | str]) -> dict[str, Any]:
        ids = [_resource(r, None)[0] for r in resources]
        return cast(dict[str, Any], await self._raw.agents.resources_plan_resources({"resources": ids}))

    async def add(self, resource: dict[str, Any] | str, *, kind: str | None = None, **fields: Any) -> dict[str, Any]:
        rid, kind = _resource(resource, kind)
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], await service.resources_copy_resource(rid, fields))

    async def update(self, copy: dict[str, Any], *, confirm: bool = False) -> dict[str, Any]:
        kind, record, rid = _copy(copy)
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], await service.resources_take_update(rid, record, {"confirm": confirm}))

    async def remove(self, copy: dict[str, Any]) -> None:
        kind, record, _ = _copy(copy)
        service, op = _DELETES[kind]
        await getattr(getattr(self._raw, service), op)(record)


class AsyncUsage:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self, **query: Any) -> list[dict[str, Any]]:
        return _rows(await self._raw.tools.executions_list_executions(**query))


class AsyncSecrets:
    """The team's secrets (Settings > Secrets). A value goes in and is never read back: no answer carries it."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self) -> list[dict[str, Any]]:
        return _rows(await self._raw.tools.secrets_list_secrets())

    async def create(self, name: str, value: str, *, teams: list[str] | None = None) -> dict[str, Any]:
        """Stores a secret as the team's; `teams` also shares it with other teams of the caller."""
        body: dict[str, Any] = {"name": name, "value": value, **({"teams": teams} if teams else {})}
        return cast(dict[str, Any], await self._raw.tools.secrets_create_secret(body))

    async def rotate(self, name: str, value: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.secrets_rotate_secret(name, {"value": value}))

    async def rename(self, name: str, new_name: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.secrets_rename_secret(name, {"name": new_name}))

    async def delete(self, name: str) -> Any:
        return await self._raw.tools.secrets_delete_secret(name)


class AsyncEgress:
    """The hosts and address ranges tools may reach (Settings > Egress); only a Security admin changes them."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.egress_allow_list())

    async def allow_host(self, host: str, note: str = "") -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.egress_add_host({"value": host, "note": note}))

    async def allow_range(self, cidr: str, note: str = "") -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.egress_add_range({"value": cidr, "note": note}))

    async def remove_host(self, host: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.egress_remove_host({"value": host}))

    async def remove_range(self, cidr: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.tools.egress_remove_range({"value": cidr}))


class Policies:
    """The team's settings a Security admin changes (Settings > Policies), such as `toolWritesNeedApproval`. They
    belong to the team the client acts in."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def get(self, key: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.platform.policies_get_policy(key))

    def set(self, key: str, value: Any) -> dict[str, Any]:
        return cast(dict[str, Any], self._raw.platform.policies_set_policy(key, {"value": value}))


class AsyncPolicies:
    """The team's settings a Security admin changes (Settings > Policies), such as `toolWritesNeedApproval`. They
    belong to the team the client acts in."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def get(self, key: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.platform.policies_get_policy(key))

    async def set(self, key: str, value: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await self._raw.platform.policies_set_policy(key, {"value": value}))
