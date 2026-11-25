"""The provider types a connection can be made of: one JSON entry per type under `registry/providers/`, plus the folder
`OPS_MODELS_PROVIDER_REGISTRY_EXTRA` names, read and checked once at start-up. An entry names its adapter (the code
that calls the provider, `providers.ADAPTERS`), the fields a connection of it takes as a small JSON Schema, and how its
models are listed. Adding a provider is an entry, plus an adapter only when no existing one speaks its API.

A connection field is stored in one of the connection's columns (`x-column`) or is a secret (`x-secret`), saved
sealed as the account's provider key the connection's `keyRef` names: the one value when the entry has one secret
field, else a JSON object of them. No secret is ever returned. The schema keywords read are the ones listed in
`ConnectionField`; any other fails the entry, so a field never carries a rule that nothing enforces."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from ops_service_kit.http import In, Json
from ops_service_kit.names import Name80

BUILTIN = Path(__file__).resolve().parents[2] / "registry" / "providers"

# The connection columns a field may be stored in, under the wire name the connection routes use.
COLUMNS = {"base_url": "baseUrl", "api_version": "apiVersion", "region": "region"}
Auth = Literal["bearer", "x-api-key", "api-key", "sigv4", "none"]


class RegistryInvalid(ValueError):
    """An entry that cannot be served: the service does not start."""


class ModelList(In):
    """How the models a key reaches are listed: GET `{base}{path}`, rows under `items`, each named by `id`."""

    # Defaults to the connection's base URL; `{region}` is filled from the connection.
    base: str | None = None
    path: str
    auth: Auth
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    items: str = "data"
    id: str = "id"
    # Azure lists deployments: each row's underlying model is under this key.
    model_field: str | None = None
    # A prefix the provider puts on every id that chat calls do not take (Gemini's `models/`).
    id_prefix: str | None = None
    # `azure`: the base must be an Azure OpenAI resource host (`key_check.azure_host`).
    host: Literal["azure"] | None = None
    # What `{apiVersion}` in the path is when the check names none (Azure's deployments list).
    api_version: str | None = None


class ConnectionField(In):
    """One field of a connection, as a JSON Schema string property: stored in a connection column (`x-column`, the
    column's wire name) or saved sealed as the provider key (`x-secret`). A keyword not listed here fails the entry."""

    type: Literal["string"]
    title: Name80
    description: str | None = None
    default: str | None = None
    pattern: str | None = None
    enum: list[str] | None = None
    format: Literal["uri"] | None = None
    x_secret: bool = Field(default=False, alias="x-secret")
    x_column: Literal["base_url", "api_version", "region"] | None = Field(default=None, alias="x-column")

    @model_validator(mode="after")
    def _stored(self) -> ConnectionField:
        if self.x_secret == (self.x_column is not None):
            raise ValueError("a connection field is either stored in a column (x-column) or a secret (x-secret)")
        if self.pattern is not None:
            re.compile(self.pattern)
        return self


class ConnectionSchema(In):
    type: Literal["object"]
    properties: dict[str, ConnectionField]
    required: list[str] = Field(default_factory=list[str])

    @model_validator(mode="after")
    def _named(self) -> ConnectionSchema:
        for name, field in self.properties.items():
            if field.x_column is not None and COLUMNS[field.x_column] != name:
                raise ValueError(
                    f"connection field {name}: x-column {field.x_column} is named {COLUMNS[field.x_column]}"
                )
        if not set(self.required) <= set(self.properties):
            raise ValueError("connection required names fields it does not define")
        return self


class ProviderEntry(In):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")
    label: Name80
    icon: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    adapter: str
    # The provider's id in the model catalog (models.dev's); none for a type whose models are not catalogued.
    catalog: str | None = None
    # Where calls go when a connection names no base URL; `{region}` is filled from the connection.
    base_url: str | None = None
    connection: ConnectionSchema
    model_list: ModelList | None = None
    test: Literal["modelList", "none"] = "modelList"

    @property
    def schema_view(self) -> Json:
        """The connection's JSON Schema as clients read it, with its `x-secret` and `x-column` marks."""
        return self.connection.model_dump(by_alias=True, exclude_none=True, exclude_defaults=False)

    @property
    def secret_fields(self) -> list[str]:
        return [n for n, f in self.connection.properties.items() if f.x_secret]

    def problem(self, values: Mapping[str, str | None]) -> str | None:
        """The first field `values` (wire names) gets wrong for this type, naming it; None when a connection of it can
        be made. Secret fields are not checked here: they are saved under the key the connection names."""
        for name, field in self.connection.properties.items():
            if field.x_secret:
                continue
            value = values.get(name)
            if not value:
                if name in self.connection.required and not field.default:
                    return f"{name} is missing: {field.description or field.title}"
                continue
            if field.pattern and not re.fullmatch(field.pattern, value):
                return f"{name} {value!r} is not {field.description or 'in the form ' + field.pattern}"
            if field.enum and value not in field.enum:
                return f"{name} is one of {', '.join(field.enum)}"
        unknown = {n for n, v in values.items() if v} - set(self.connection.properties)
        if unknown:
            return f"{', '.join(sorted(unknown))} do not apply to {self.label} connections"
        return None

    def base_for(self, base_url: str | None, region: str | None) -> str | None:
        """Where a connection's calls go: its own base URL, else the entry's, with the region filled in."""
        base = base_url or self.base_url
        if base and "{region}" in base:
            return base.replace("{region}", region) if region else None
        return base


class Registry:
    def __init__(self, entries: Iterable[ProviderEntry]) -> None:
        self.entries = {e.id: e for e in entries}

    def get(self, type_id: str) -> ProviderEntry | None:
        return self.entries.get(type_id)

    def listed(self) -> list[ProviderEntry]:
        return sorted(self.entries.values(), key=lambda e: e.label.lower())


def load_registry(adapters: Iterable[str], *folders: Path | None) -> Registry:
    """Every entry in `folders`, in order, each checked: a file that is not an entry, an adapter no code registers,
    or an id given twice raises RegistryInvalid naming the file."""
    known = set(adapters)
    entries: dict[str, ProviderEntry] = {}
    for folder in folders:
        if folder is None:
            continue
        if not folder.is_dir():
            raise RegistryInvalid(f"provider registry folder {folder} does not exist")
        for path in sorted(folder.glob("*.json")):
            try:
                entry = ProviderEntry.model_validate(json.loads(path.read_text()))
            except (ValueError, ValidationError) as e:
                raise RegistryInvalid(f"provider registry entry {path.name}: {e}") from e
            if entry.adapter not in known:
                raise RegistryInvalid(
                    f"provider registry entry {path.name}: adapter {entry.adapter!r} is not one of {sorted(known)}"
                )
            if entry.id in entries:
                raise RegistryInvalid(f"provider registry entry {path.name}: type {entry.id} is defined twice")
            entries[entry.id] = entry
    return Registry(entries.values())
