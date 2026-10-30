"""Offline checks of a plugin: what `ops plugin validate` prints and what each service's loader refuses a plugin for.

One list of problems, each naming where it is, so a plugin is refused for every reason at once rather than one per
run. A plugin with any problem is not loaded."""

from __future__ import annotations

import importlib
import inspect
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
    SDK_MAJOR,
    SIGN_IN_KINDS,
    InputField,
    Manifest,
    ManifestError,
    Request,
    Tool,
    read,
)
from .paging import QUERY_VAR
from .plugin import MARK

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
# An enum value is written into a query as it stands, so it may hold nothing that could end a string or add a clause.
ENUM_VALUE = re.compile(r"^[A-Za-z0-9 _.-]*$")
MAX_DEPTH = 3


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
                f"{', '.join(personal)} needs a kind that holds each person's own token "
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
    for i, host in enumerate(manifest.egress):
        out += _placeholders(manifest, host, f"egress[{i}]")
    out += _placeholders(manifest, manifest.endpoint, "endpoint")
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
        if t.request is not None:
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
        for role, name in (("list_items", s.list), ("get_item", s.get), ("list_deleted", s.deleted)):
            if name is None:
                continue
            t = manifest.tool(name)
            if t is None:
                out.append(Problem(where, f"names no tool {name}"))
            elif t.knowledge != role:
                out.append(Problem(where, f"{name} is not marked knowledge: {role}"))
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
    return out


def validate(root: Path) -> tuple[Manifest | None, list[Problem]]:
    """The plugin in `root` (the folder holding plugin.yaml) and its problems; no manifest when it does not parse."""
    try:
        manifest = read(root / "plugin.yaml")
    except ManifestError as e:
        return None, [Problem("plugin.yaml", p) for p in e.problems]
    return manifest, check(manifest, root)
