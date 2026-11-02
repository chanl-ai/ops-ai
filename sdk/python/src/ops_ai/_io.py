"""Load a definition or payload from a dict, a file path, or YAML/JSON text. YAML needs PyYAML; JSON always works."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

Definition = dict[str, Any] | str | Path


def _yaml_load(text: str) -> Any:
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:
        raise ValueError("YAML needs PyYAML; pass JSON or install pyyaml") from e
    return yaml.safe_load(text)


def _yaml_dump(data: Any) -> str:
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:
        raise ValueError("YAML needs PyYAML; install pyyaml") from e
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def load_data(source: Any) -> Any:
    """A dict as-is; a path or YAML/JSON text parsed. `key=value` pairs stay for the CLI to handle."""
    if source is None or isinstance(source, (dict, list)):
        return source
    text = Path(source).read_text() if _looks_like_path(source) else str(source)
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(text)
    return _yaml_load(text)


def load_definition(source: Definition) -> dict[str, Any]:
    """A schema v2 workflow object from a dict, a file, or YAML/JSON text."""
    if isinstance(source, dict):
        return source
    data = load_data(source)
    if not isinstance(data, dict):
        raise ValueError("a workflow definition is a mapping")
    return data


def definition_body(source: Definition) -> dict[str, Any]:
    """The validate/create body: YAML or JSON text when the source is a file or string, else the object."""
    if isinstance(source, dict):
        return {"definition": source}
    if _looks_like_path(source):
        return {"yaml": Path(source).read_text()}
    text = str(source)
    return {"yaml": text}


def dump_definition(definition: dict[str, Any], fmt: str) -> str:
    if fmt == "yaml":
        return _yaml_dump(definition)
    if fmt == "json":
        return json.dumps(definition, indent=2, ensure_ascii=False) + "\n"
    raise ValueError(f"format {fmt} is not yaml or json")


def as_folder(source: str | Path) -> Path | None:
    path = Path(source)
    return path if path.is_dir() else None


def definition_in(source: str | Path | dict[str, Any]) -> Definition:
    """A file or object a workflow command accepts: the folder's workflow.yaml when a directory is given."""
    if isinstance(source, dict):
        return source
    folder = as_folder(source)
    if folder is None:
        return Path(source)
    for name in ("resources/workflow.yaml", "workflow.yaml"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{folder} has no resources/workflow.yaml or workflow.yaml")


def _looks_like_path(source: Any) -> bool:
    if not isinstance(source, str | Path):
        return False
    path = Path(source)
    return path.exists() or (isinstance(source, str) and ("/" in source or source.endswith((".yaml", ".yml", ".json"))))
