"""`ops.templates`: what a team can start from (agents, skills, workflows, guardrails, case types, task types and
document types from the packs and apps that are on for the team), and installing one as the team's own copy.

A template is named `<source>:<id>`, for example `plugin:opsai.starters:doc-coauthoring`. Document types are kept by
documents-service and every other kind by agents-service, so a list without a kind reads both."""

from __future__ import annotations

from typing import Any, cast

DOCUMENT_TYPE = "document_type"


def _ref(template: dict[str, Any] | str) -> str:
    return template if isinstance(template, str) else f"{template['source']}:{template['id']}"


def _kind_of(found: list[dict[str, Any]], ref: str) -> str | None:
    return next((str(t["kind"]) for t in found if f"{t['source']}:{t['id']}" == ref), None)


class Templates:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, *, kind: str | None = None, source: str | None = None) -> list[dict[str, Any]]:
        """Every template offered to the team, each with its state, the team's copies and whether you may add it
        (`canAdd`). `kind` keeps one kind; `source` keeps one pack or app (`plugin:<id>`)."""
        out: list[dict[str, Any]] = []
        if kind != DOCUMENT_TYPE:
            out += cast(list[dict[str, Any]], self._raw.agents.templates_list_templates(kind=kind, source=source))
        if kind in (None, DOCUMENT_TYPE):
            docs = cast(list[dict[str, Any]], self._raw.documents.templates_list_templates(kind=kind))
            out += [t for t in docs if source in (None, t.get("source"))]
        return out

    def install(self, template: dict[str, Any] | str, *, kind: str | None = None, **fields: Any) -> dict[str, Any]:
        """Adds the template to the team as the team's own copy, through the same checks as creating one of its kind
        by hand. `fields` are the copy's own values (`name`, `knowledgeBases`, `modelAlias`, `bindings`)."""
        ref = _ref(template)
        kind = kind or (None if isinstance(template, str) else str(template.get("kind") or "")) or None
        if kind is None:
            # agents-service keeps every kind but document types, so it is asked first.
            mine = cast(list[dict[str, Any]], self._raw.agents.templates_list_templates(source=ref.rsplit(":", 1)[0]))
            kind = _kind_of(mine, ref) or DOCUMENT_TYPE
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], service.resources_copy_resource(ref, fields))


class AsyncTemplates:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    async def list(self, *, kind: str | None = None, source: str | None = None) -> list[dict[str, Any]]:
        """As `Templates.list`."""
        out: list[dict[str, Any]] = []
        if kind != DOCUMENT_TYPE:
            out += cast(list[dict[str, Any]], await self._raw.agents.templates_list_templates(kind=kind, source=source))
        if kind in (None, DOCUMENT_TYPE):
            docs = cast(list[dict[str, Any]], await self._raw.documents.templates_list_templates(kind=kind))
            out += [t for t in docs if source in (None, t.get("source"))]
        return out

    async def install(
        self, template: dict[str, Any] | str, *, kind: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """As `Templates.install`."""
        ref = _ref(template)
        kind = kind or (None if isinstance(template, str) else str(template.get("kind") or "")) or None
        if kind is None:
            source = ref.rsplit(":", 1)[0]
            mine = cast(list[dict[str, Any]], await self._raw.agents.templates_list_templates(source=source))
            kind = _kind_of(mine, ref) or DOCUMENT_TYPE
        service = self._raw.documents if kind == DOCUMENT_TYPE else self._raw.agents
        return cast(dict[str, Any], await service.resources_copy_resource(ref, fields))


__all__ = ["AsyncTemplates", "Templates"]
