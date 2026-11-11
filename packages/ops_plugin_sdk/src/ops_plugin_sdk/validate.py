"""Offline checks of a plugin: what `opsai plugin validate` prints and what each service's loader refuses a plugin for.

One list of problems, each naming where it is, so a plugin is refused for every reason at once rather than one per
run. A plugin with any problem is not loaded."""

from __future__ import annotations

import importlib
import inspect
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .manifest import (
    MAX_ITEMS,
    OPERATION_NAME,
    PER_PERSON_KINDS,
    PLATFORM_AUTHORIZE_PARAMS,
    SDK_MAJOR,
    SIGN_IN_HEADERS,
    SIGN_IN_KINDS,
    InputField,
    Manifest,
    ManifestError,
    Request,
    Tool,
    read,
)
from .paging import QUERY_VAR, steps
from .plugin import MARK

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
# An enum value is written into a query as it stands, so it may hold nothing that could end a string or add a clause.
ENUM_VALUE = re.compile(r"^[A-Za-z0-9 _.-]*$")
MAX_DEPTH = 3
# tools-service resolves `{{NAME}}` in an operation's path, query and headers from the calling team's secrets
# (executor.SECRET_REF), so a plugin template may never hold one: it would send the team's secret to the plugin's host.
SECRET_REF = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
OAUTH_KINDS = ("oauth2_client_credentials", "oauth2_auth_code")


@dataclass(frozen=True)
class Problem:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def _placeholders(manifest: Manifest, text: str, where: str) -> list[Problem]:
    return [
        Problem(where, f"{{{name}}} names no setting")
        for name in PLACEHOLDER.findall(text)
        if name not in manifest.settings
    ]


def _inputs(name: str, field: InputField, where: str, depth: int = 0) -> list[Problem]:
    """Each input's own problems, nested ones included: enum values, patterns, and how deep and long it may grow."""
    out: list[Problem] = []
    for v in field.enum or []:
        if isinstance(v, str) and not ENUM_VALUE.match(v):
            out.append(Problem(where, f"enum value {v} may hold only letters, digits, space, _, - and ."))
    if field.pattern is not None:
        try:
            re.compile(field.pattern)
        except re.error as e:
            out.append(Problem(where, f"the pattern of {name} does not compile: {e}"))
    if field.type in ("object", "array"):
        if depth >= MAX_DEPTH:
            return [*out, Problem(where, f"{re.split(r'[.\[]', name, maxsplit=1)[0]} nests past three levels")]
        if field.type == "array" and field.max_items > MAX_ITEMS:
            out.append(Problem(where, f"{name} may hold at most {MAX_ITEMS} items"))
        for k, sub in (field.properties or {}).items():
            out += _inputs(f"{name}.{k}", sub, where, depth + 1)
        if field.items is not None:
            out += _inputs(f"{name}[]", field.items, where, depth + 1)
    return out


def _paging(tool: Tool, request: Request, where: str) -> list[Problem]:
    paging = request.paging
    if paging is None:
        return []
    out: list[Problem] = []
    if tool.access != "read":
        out.append(Problem(where, "only a read pages"))
    if paging.rule == "link" and not paging.next:
        out.append(Problem(where, "a link rule names the answer field that holds the next page's address (next)"))
    if paging.rule == "token" and not paging.next:
        out.append(Problem(where, "a token rule names the answer field that holds the token (next)"))
    if paging.rule == "token" and not paging.param:
        out.append(Problem(where, "a token rule names the parameter the token is sent back as (param)"))
    if paging.rule == "offset" and not (paging.limit and paging.items):
        out.append(Problem(where, "an offset rule names the answer's list (items) and the page size (limit)"))
    if paging.rule == "page" and not paging.limit:
        out.append(Problem(where, "a page rule names the page size (limit)"))
    if paging.rule == "link_header" and (paging.next or paging.items):
        out.append(Problem(where, "a link_header rule reads the Link header and names no answer field"))
    return out


def _query(tool: Tool, request: Request, where: str) -> list[Problem]:
    """Every value a query template takes must have an enum or a format, which tools-service checks and escapes; a
    pattern alone cannot keep a value from changing the query it is put into."""
    out: list[Problem] = []
    for param, template in request.query.items():
        for m in QUERY_VAR.finditer(template):
            name = m.group(1)
            field = tool.input.get(name)
            if field is None:
                out.append(Problem(where, f"{{{{{name}}}}} in the query names no input"))
                continue
            leaf = field.items or InputField() if field.type == "array" else field
            if leaf.enum is None and leaf.format is None:
                said = (
                    f"{name} has only a pattern, which is for path segments; a query needs an enum or a format"
                    if leaf.pattern
                    else f"{name} is used in a query and needs an enum or a format"
                )
                out.append(Problem(where, said))
            if leaf.format == "soql_string" and not (
                template[: m.start()].endswith("'") and template[m.end() :].startswith("'")
            ):
                out.append(Problem(where, f"{{{{{name}}}}} is a soql_string and goes between single quotes ({param})"))
    return out


def _host_part(template: str) -> str:
    """The host a URL template reaches, as written: `api.atlassian.com`, or `{base_url}` for a setting holding it."""
    rest = template.split("://", 1)[1] if "://" in template else template
    return rest.split("/", 1)[0].lower()


def _settings_text(manifest: Manifest, text: str, where: str, what: str) -> list[Problem]:
    """A header or sign-in parameter value: fixed text and {setting}, never `{{` and never a secret setting."""
    if "{{" in text:
        return [Problem(where, f"{what} holds {{{{, which could name a secret; use fixed text or {{setting}}")]
    out = _placeholders(manifest, text, where)
    for name in PLACEHOLDER.findall(text):
        setting = manifest.settings.get(name)
        if setting is not None and setting.secret:
            out.append(Problem(where, f"{what} names {name}, a secret setting; a secret goes only in the sign-in"))
    return out


def _headers(manifest: Manifest, headers: dict[str, str], where: str) -> list[Problem]:
    refused = set(SIGN_IN_HEADERS)
    key_name = manifest.connection.api_key.name.lower() if manifest.connection.api_key else None
    out: list[Problem] = []
    for name, value in headers.items():
        at_ = f"{where}.{name}"
        if not HEADER_NAME.match(name):
            out.append(Problem(at_, "is not a header name"))
        elif name.lower() in refused or name.lower() == key_name:
            out.append(Problem(at_, "carries the sign-in; the connection sends it, never a plugin header"))
        out += _settings_text(manifest, value, at_, "a header")
    return out


def _quoted_inputs(body: str) -> list[str]:
    """The `{{input}}`s a JSON body template puts inside a JSON string, where its own quotes would break the JSON."""
    found: list[str] = []
    in_string = escaped = False
    i = 0
    while i < len(body):
        c = body[i]
        if in_string and (m := QUERY_VAR.match(body, i)):
            found.append(m.group(1))
            i = m.end()
            continue
        if escaped:
            escaped = False
        elif c == "\\" and in_string:
            escaped = True
        elif c == '"':
            in_string = not in_string
        i += 1
    return found


def _body_problems(tool: Tool, body: str, where: str) -> list[Problem]:
    """A JSON body is sent with each `{{input}}` written as JSON, quotes included: one inside quotes, one naming no
    input, or a template that is not JSON once the inputs are written in would send a body the system cannot read."""
    out = [
        Problem(where, f"{{{{{name}}}}} sits inside quotes in the body; it is written as JSON, so leave it bare")
        for name in _quoted_inputs(body)
    ]
    out += [
        Problem(where, f"{{{{{name}}}}} in the body names no input")
        for name in QUERY_VAR.findall(body)
        if name not in tool.input
    ]
    try:
        json.loads(QUERY_VAR.sub("null", body))
    except ValueError:
        out.append(Problem(where, "the body is not JSON once each {{input}} is written in"))
    return out


def _request_text(tool: Tool, request: Request, where: str) -> list[Problem]:
    """A secret reference anywhere a request is built from, and the form body's own rules."""
    texts = [request.path, request.body or "", *request.query.values(), *(request.form or {}).values()]
    out = [
        Problem(where, f"{m} is a secret reference; a plugin's requests carry no secret")
        for t in texts
        for m in SECRET_REF.findall(t)
    ]
    if request.body is not None:
        out += _body_problems(tool, request.body, where)
    if request.form is not None:
        if request.body is not None:
            out.append(Problem(where, "a request has a JSON body or a form, not both"))
        if request.method in ("GET", "DELETE"):
            out.append(Problem(where, f"a {request.method} sends no form"))
        for field, template in request.form.items():
            for name in QUERY_VAR.findall(template):
                if name not in tool.input:
                    out.append(Problem(where, f"{{{{{name}}}}} in form field {field} names no input"))
    paging = request.paging
    for path in (paging.next, paging.items) if paging else ():
        if path and "[" in path:
            out.append(Problem(where, f"the paging path {path} may name fields only, not list positions"))
    return out


def _amount(tool: Tool, where: str) -> list[Problem]:
    if tool.amount_max is None:
        return []
    amount = tool.input.get("amount")
    if amount is None or amount.type not in ("number", "integer"):
        return [Problem(where, "amount_max needs a number input named amount, which the limit reads")]
    if tool.request is not None and tool.request.paging is not None:
        return [Problem(where, "a paged tool cannot have amount_max: its inputs are optional on a next page")]
    return []


def _sign_in_steps(manifest: Manifest) -> list[Problem]:
    c = manifest.connection
    out: list[Problem] = []
    for name, value in c.authorize_params.items():
        where = f"connection.authorize_params.{name}"
        if name.lower() in PLATFORM_AUTHORIZE_PARAMS:
            out.append(Problem(where, "is set by the platform for every sign-in; a plugin cannot replace it"))
        out += _settings_text(manifest, value, where, "a sign-in parameter")
    if c.authorize_params and "oauth2_auth_code" not in c.kinds:
        out.append(Problem("connection.authorize_params", "only a plugin that signs in with an account has these"))
    if c.client_auth is not None and not set(c.kinds) & set(OAUTH_KINDS):
        out.append(Problem("connection.client_auth", "only an OAuth plugin sends its client on a token call"))
    lookup = c.after_sign_in
    named = [k for k, s in manifest.settings.items() if s.after_sign_in]
    if lookup is None:
        out += [Problem(f"settings.{k}", "is filled after sign-in, but the plugin has no after_sign_in") for k in named]
        return out
    where = "connection.after_sign_in"
    setting = manifest.settings.get(lookup.setting)
    if setting is None or not setting.after_sign_in or setting.from_token or lookup.setting in c.from_token:
        out.append(Problem(where, f"{lookup.setting} must be a setting marked after_sign_in, and not from_token"))
    out += [
        Problem(f"settings.{k}", "is marked after_sign_in, but the lookup fills another")
        for k in named
        if k != lookup.setting
    ]
    if steps(lookup.read) is None:
        out.append(Problem(where, f"read {lookup.read} is not a path such as [0].id or .accounts[0].base_uri"))
    if "{{" in lookup.url:
        out.append(Problem(where, "the lookup address holds {{, which could name a secret"))
    out += _placeholders(manifest, lookup.url, where)
    if lookup.url.startswith("/"):
        if not c.token_url:
            out.append(Problem(where, "a lookup path is on the sign-in host, and this plugin has no token_url"))
        host = _host_part(c.token_url or "")
    elif lookup.url.startswith("https://") or lookup.url.startswith("{"):
        host = _host_part(lookup.url)
    else:
        out.append(Problem(where, "the lookup address is https, or a path on the sign-in host"))
        host = ""
    if host and host not in {_host_part(e) for e in manifest.egress}:
        out.append(Problem(where, f"the lookup reaches {host}, which is not one of the plugin's egress hosts"))
    if not c.token_hosts:
        out.append(Problem("connection.token_hosts", "a lookup after sign-in needs the host suffixes it may name"))
    return out


# A choice's value must be of its setting's type; bool is checked before int, which it would otherwise pass as.
_TYPES: dict[str, tuple[type, ...]] = {"string": (str,), "number": (int, float), "integer": (int,), "boolean": (bool,)}


def _of_type(value: Any, kind: str) -> bool:
    if isinstance(value, bool):
        return kind == "boolean"
    return isinstance(value, _TYPES[kind])


def _offered(manifest: Manifest) -> list[Problem]:
    """A setting's choices and its typed host, a refused sign-in's messages, and the settings an app credential holds:
    what tools-service checks a team's value against and says when a sign-in is refused."""
    out: list[Problem] = []
    for name, s in manifest.settings.items():
        where = f"settings.{name}"
        for c in s.choices or []:
            if not _of_type(c.value, s.type):
                out.append(Problem(where, f"the choice {c.value!r} is not a {s.type}, the setting's type"))
        if s.other is None:
            continue
        if s.type != "string":
            out.append(Problem(where, "other is a typed host, so its setting is a string"))
        if s.other.value.count("{host}") != 1:
            out.append(Problem(where, "other.value names {host} once, where the typed host goes"))
        if not s.other.hosts:
            out.append(Problem(where, "other names the host suffixes a typed host must end in (hosts)"))
        for suffix in (*s.other.hosts, *s.other.test_account_hosts):
            if not suffix.startswith(".") or len(suffix) < 3:
                out.append(Problem(where, f"the host suffix {suffix} starts with a dot, so it matches whole labels"))
    c = manifest.connection
    for i, e in enumerate(c.sign_in_errors):
        where = f"connection.sign_in_errors[{i}]"
        if not (e.say or "").strip():
            out.append(Problem(where, f"{e.error} says nothing; say is the sentence a person reads"))
        if e.who is None:
            out.append(Problem(where, f"{e.error} names nobody to act; who is person or admin"))
    for name in c.credential_settings:
        setting = manifest.settings.get(name)
        if setting is None:
            out.append(Problem("connection.credential_settings", f"{name} names no setting"))
        elif setting.at_sign_in:
            out.append(Problem("connection.credential_settings", f"{name} is filled at sign-in, not by an app"))
    for name, setting in manifest.settings.items():
        if setting.asked is not None and setting.at_sign_in:
            out.append(Problem(f"settings.{name}", f"{name} is filled at sign-in, so no window asks for it"))
    return out


def _function(root: Path, path: str) -> tuple[Any, str | None]:
    module, _, name = path.partition(":")
    added = str(root.parent)
    sys.path.insert(0, added)
    try:
        fn = getattr(importlib.import_module(module), name, None)
    except Exception as e:  # an import that raises is the plugin's problem, reported with its message
        return None, f"cannot import {module}: {e}"
    finally:
        sys.path.remove(added)
    if fn is None:
        return None, f"{module} has no {name}"
    return fn, None


# Shown under an account's name on one line, so a few values at most.
IDENTITY_MAX = 3


def _identity(manifest: Manifest) -> list[Problem]:
    """Each `connection.identity` name is one of the plugin's settings and never a secret, since it is shown under the
    account's name to everyone who sees the account; at most IDENTITY_MAX."""
    names = manifest.connection.identity
    out: list[Problem] = []
    if len(names) > IDENTITY_MAX:
        out.append(Problem("connection.identity", f"names {len(names)} settings; at most three fit under a name"))
    for name in names:
        setting = manifest.settings.get(name)
        if setting is None:
            out.append(Problem(f"connection.identity.{name}", f"{name} is not one of the plugin's settings"))
        elif setting.secret:
            out.append(Problem(f"connection.identity.{name}", f"{name} is a secret, which is never shown"))
    return out


def _package(manifest: Manifest) -> list[Problem]:
    """A package app (`connection.runs_on`) signs in through the app it runs on and no other way; `requires` and its
    check belong to a package only, and the check names each object with {name}."""
    c = manifest.connection
    out: list[Problem] = []
    if c.runs_on is not None:
        if c.kinds != ["none"]:
            out.append(Problem("connection.runs_on", "a package signs in through the app it runs on: kinds: [none]"))
        if c.runs_on == manifest.id:
            out.append(Problem("connection.runs_on", "a plugin cannot run on itself"))
    elif c.requires or c.requires_check:
        out.append(Problem("connection.requires", "requires names objects of the app a package runs on: set runs_on"))
    if c.requires_check is not None and (not c.requires_check.startswith("/") or "{name}" not in c.requires_check):
        out.append(
            Problem("connection.requires_check", "a package check is a path from / naming each object as {name}")
        )
    if c.requires and c.requires_check is None:
        out.append(Problem("connection.requires_check", "required objects need the path that checks each, with {name}"))
    return out


def check(manifest: Manifest, root: Path) -> list[Problem]:
    out: list[Problem] = []
    if manifest.sdk != SDK_MAJOR:
        out.append(Problem("sdk", f"built for SDK {manifest.sdk}; this platform runs SDK {SDK_MAJOR}"))
    for kind in manifest.connection.kinds:
        if kind not in SIGN_IN_KINDS:
            out.append(Problem("connection.kinds", f"unknown sign-in kind {kind}; one of {', '.join(SIGN_IN_KINDS)}"))
    c = manifest.connection
    if "api_key" in c.kinds and c.api_key is None:
        out.append(Problem("connection.api_key", "an api_key plugin says how its key is sent: placement and name"))
    personal = [s for s in c.sign_in if s != "team"]
    if personal and not set(c.kinds) & set(PER_PERSON_KINDS):
        out.append(
            Problem(
                "connection.sign_in",
                f"{', '.join(personal)} needs a kind that holds each person's own credential "
                f"({', '.join(PER_PERSON_KINDS)}); {', '.join(c.kinds)} signs in as the team only",
            )
        )
    for name in manifest.connection.from_token:
        setting = manifest.settings.get(name)
        if setting is None or not setting.from_token:
            out.append(Problem(f"connection.from_token.{name}", "must name a setting marked from_token"))
    if manifest.connection.from_token and not manifest.connection.token_hosts:
        out.append(
            Problem("connection.token_hosts", "a setting read from the token needs the host suffixes it may name")
        )
    out += _identity(manifest)
    out += _package(manifest)
    if manifest.connection.runs_on is None:
        # A package's endpoint and egress render with the settings of the app it runs on, which this folder does not
        # hold; tools-service renders them at each call and refuses one whose app is not installed.
        for i, host in enumerate(manifest.egress):
            out += _placeholders(manifest, host, f"egress[{i}]")
        out += _placeholders(manifest, manifest.endpoint, "endpoint")
    out += _headers(manifest, manifest.headers, "headers")
    out += _sign_in_steps(manifest)
    out += _offered(manifest)
    seen: set[str] = set()
    for t in manifest.tools:
        where = f"tools.{t.name}"
        if t.name in seen:
            out.append(Problem(where, "two tools share this name"))
        seen.add(t.name)
        if not OPERATION_NAME.match(manifest.operation(t.name)):
            out.append(Problem(where, f"{manifest.operation(t.name)} is not a valid operation name"))
        if t.knowledge and t.access != "read":
            out.append(Problem(where, f"a {t.knowledge} tool must be a read, so a sync never waits for approval"))
        if t.knowledge == "get_item" and t.request is not None and "id" not in t.input:
            out.append(Problem(where, "a get_item tool takes an id"))
        for n, f in t.input.items():
            out += _inputs(n, f, where)
        out += _headers(manifest, t.headers, f"{where}.headers")
        out += _amount(t, where)
        if t.function is not None and t.headers:
            out.append(Problem(f"{where}.headers", "a Python tool takes the plugin's headers only"))
        if t.request is not None:
            out += _request_text(t, t.request, where)
            unknown = set(PLACEHOLDER.findall(t.request.path)) - set(t.input) - set(manifest.settings)
            out += [Problem(where, f"{{{n}}} in the path names no input or setting") for n in sorted(unknown)]
            out += _paging(t, t.request, where)
            out += _query(t, t.request, where)
        if t.function is not None:
            fn, error = _function(root, t.function)
            if error:
                out.append(Problem(where, error))
                continue
            mark = getattr(fn, MARK, None)
            if mark is None:
                out.append(Problem(where, f"{t.function} is not marked @tool"))
            elif mark["access"] != t.access:
                out.append(Problem(where, f"@tool says {mark['access']}, the manifest says {t.access}"))
            params = list(inspect.signature(fn).parameters)
            if not params or params[0] != "ctx":
                out.append(Problem(where, f"{t.function} takes the context first, as ctx"))
            if t.knowledge == "list_items" and not {"since", "cursor"} <= set(params):
                out.append(Problem(where, "a list_items function takes since and cursor"))
            # tools-service checks each call against the declared inputs, so a parameter left undeclared can never be
            # passed, and an input the function does not take fails every call that gives it.
            taken = set(params[1:])
            for n in sorted(taken - set(t.input)):
                out.append(Problem(where, f"{n} is a parameter of {t.function} but not a declared input"))
            for n in sorted(set(t.input) - taken):
                out.append(Problem(where, f"input {n} is not a parameter of {t.function}"))
        if t.knowledge == "list_items" and any(t.input[n].required for n in ("since", "cursor") if n in t.input):
            out.append(
                Problem(where, "since and cursor are optional inputs of a list_items tool; a first page has neither")
            )
    for s in manifest.knowledge_sources:
        where = f"knowledge_sources.{s.name}"
        for n, f in s.inputs.items():
            out += _inputs(n, f, f"{where}.inputs")
        if s.egress_from is not None and s.egress_from not in s.inputs:
            out.append(Problem(where, f"egress_from names {s.egress_from}, which is not one of its inputs"))
        for role, name in s.tools():
            t = manifest.tool(name)
            if t is None:
                out.append(Problem(where, f"names no tool {name}"))
            elif t.knowledge != role:
                out.append(Problem(where, f"{name} is not marked knowledge: {role}"))
            elif s.inputs and "source" not in t.input:
                # kb-service sends a source's own settings to each of its tools as `source`.
                out.append(Problem(where, f"{name} takes no source input, though the source has inputs"))
    for tpl in manifest.templates:
        where = f"templates.{tpl.id}"
        path = (root / tpl.path).resolve()
        if root.resolve() not in path.parents:
            out.append(Problem(where, f"{tpl.path} is outside the plugin"))
            continue
        try:
            yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as e:
            out.append(Problem(where, f"{tpl.path} does not parse: {e}"))
        for name in tpl.requires.tools:
            if manifest.tool(name) is None:
                out.append(Problem(where, f"requires the tool {name}, which this plugin does not have"))
        ids = {t.id for t in manifest.templates}
        for name in tpl.requires.resources:
            if name not in ids or name == tpl.id:
                out.append(Problem(where, f"requires the resource {name}, which is no other template of this plugin"))
    return out


def validate(root: Path) -> tuple[Manifest | None, list[Problem]]:
    """The plugin in `root` (the folder holding plugin.yaml) and its problems; no manifest when it does not parse."""
    try:
        manifest = read(root / "plugin.yaml")
    except ManifestError as e:
        return None, [Problem("plugin.yaml", p) for p in e.problems]
    return manifest, check(manifest, root)
