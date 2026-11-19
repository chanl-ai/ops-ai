"""No service depends on another service's code: services talk over their APIs through
`ops_identity.ServiceClient` and share code only through packages/. By failure mode: an import of another service's
package coming back in source or tests; a service call written by hand (its own token minting next to a raw HTTP
client) instead of through ServiceClient; a shape one service sends and another reads, described differently by the
two (the reader refuses the sender's new field and answers 500); and a scan that finds nothing because it reads
nothing (first run on a file that breaks it)."""

from __future__ import annotations

import ast
import importlib
import json
import pkgutil
from pathlib import Path
from typing import Any

import ops_contracts
from ops_contracts.templates import ServiceShape

ROOT = Path(__file__).resolve().parents[2]
# Each service's own package, which no other service may import.
PACKAGES = {
    "agents-service": "ops_agents",
    "tools-service": "ops_tools",
    "kb-service": "ops_kb",
    "files-service": "ops_files",
    "documents-service": "ops_documents",
    "models-service": "ops_models",
    "platform-service": "ops_platform",
}
# What remains to move (the tool catalog leaves agents-service; the gateway tests move to tools-service).
# The list only shrinks: an import not on it fails, and an entry that no longer matches fails too.
KNOWN = {
    "services/tools-service/src/ops_tools/__main__.py: ops_agents",
    "services/tools-service/src/ops_tools/tools.py: ops_agents",
    "services/tools-service/src/ops_tools/registry.py: ops_agents",
    "services/tools-service/scripts/check_openapi.py: ops_agents",
    "services/tools-service/tests/conftest.py: ops_agents",
    "services/tools-service/tests/test_cors.py: ops_agents",
    "services/tools-service/tests/test_send_reply.py: ops_agents",
    "services/tools-service/tests/test_mailbox_senders.py: ops_agents",
    "services/agents-service/tests/gateway/conftest.py: ops_tools",
    "services/agents-service/tests/gateway/test_gateway_policy.py: ops_tools",
    "services/agents-service/experiments/e3_gateway_approval_token.py: ops_tools",
}


def offences(services: Path) -> set[str]:
    """`<file>: <package>` for each Python file under a service that imports another service's package."""
    found: set[str] = set()
    for service, own in PACKAGES.items():
        for path in sorted((services / service).rglob("*.py")):
            if ".venv" in path.parts or "node_modules" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom) and node.level == 0
                    else []
                )
                for name in names:
                    top = name.split(".")[0]
                    if top in PACKAGES.values() and top != own:
                        found.add(f"{path.relative_to(services.parent).as_posix()}: {top}")
    return found


def test_the_scan_finds_an_import_of_another_services_package(tmp_path: Path) -> None:
    src = tmp_path / "services" / "kb-service" / "src" / "ops_kb"
    src.mkdir(parents=True)
    (src / "app.py").write_text("import ops_kb.store\nfrom ops_agents.api import auth\n")
    assert offences(tmp_path / "services") == {"services/kb-service/src/ops_kb/app.py: ops_agents"}


def test_no_service_imports_another_services_code() -> None:
    found = offences(ROOT / "services")
    assert len(list((ROOT / "services").glob("*/src"))) >= 6, "the scan reads too few services"
    assert found - KNOWN == set(), "new cross-service imports:\n" + "\n".join(sorted(found - KNOWN))
    assert KNOWN - found == set(), "moved already, take off KNOWN:\n" + "\n".join(sorted(KNOWN - found))


# Raw HTTP clients stay for calls outside the platform (providers, a bank's API); a service token minted outside
# ops_identity is the mark of a call to another service written by hand. None is left; keep it that way.
MINTERS_KNOWN: set[str] = set()


def minters(root: Path) -> set[str]:
    """Each source file outside ops_identity that calls `mint_service_token`."""
    found: set[str] = set()
    for path in sorted([*root.glob("services/*/src/**/*.py"), *root.glob("packages/*/src/**/*.py")]):
        if ".venv" in path.parts or "ops_identity" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name == "mint_service_token":
                    found.add(path.relative_to(root).as_posix())
    return found


def test_the_scan_finds_a_service_call_written_by_hand(tmp_path: Path) -> None:
    src = tmp_path / "services" / "kb-service" / "src" / "ops_kb"
    src.mkdir(parents=True)
    (src / "calls.py").write_text(
        "import httpx\nfrom ops_identity import mint_service_token\nt = mint_service_token(s)\n"
    )
    (src / "fine.py").write_text("import httpx\nhttpx.AsyncClient(base_url='https://bank.example')\n")
    own = tmp_path / "packages" / "ops_identity" / "src" / "ops_identity"
    own.mkdir(parents=True)
    (own / "client.py").write_text("t = mint_service_token(s)\n")
    assert minters(tmp_path) == {"services/kb-service/src/ops_kb/calls.py"}


def test_every_service_call_goes_through_service_client() -> None:
    found = minters(ROOT)
    assert found - MINTERS_KNOWN == set(), "a service call written by hand; use ServiceClient:\n" + "\n".join(
        sorted(found - MINTERS_KNOWN)
    )
    assert MINTERS_KNOWN - found == set(), "moved already, take off MINTERS_KNOWN:\n" + "\n".join(
        sorted(MINTERS_KNOWN - found)
    )


# Reading a document is documents-service's job: the workflow runner and the agent kernel ask it through
# ops_documents_client, so the checks that score a field run in one place, never inside a worker.
NO_EXTRACT = ("packages/ops_engine", "packages/ops_agent_kernel", "services/agents-service")


def extract_importers(root: Path) -> set[str]:
    """Each Python file under NO_EXTRACT that imports ops_extract."""
    found: set[str] = set()
    for folder in NO_EXTRACT:
        for path in sorted((root / folder).rglob("*.py")):
            if ".venv" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom) and node.level == 0
                    else []
                )
                if any(n.split(".")[0] == "ops_extract" for n in names):
                    found.add(path.relative_to(root).as_posix())
    return found


def test_the_workflow_runner_and_the_kernel_never_import_the_extraction_checks(tmp_path: Path) -> None:
    planted = tmp_path / "packages" / "ops_engine" / "src" / "ops_engine" / "steps.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("from ops_extract.checks import scored\n")
    assert extract_importers(tmp_path) == {"packages/ops_engine/src/ops_engine/steps.py"}
    assert extract_importers(ROOT) == set()


# A shape services send each other is one `ops_contracts` class (a `ServiceShape`), which the sender builds and the
# reader reads. Each service's committed openapi.json is its app's own document (its scripts/check_openapi.py), so a
# service that describes such a shape itself, with other fields or under its own name, shows here.


def service_shapes() -> list[type[ServiceShape]]:
    """Every `ServiceShape` in ops_contracts, found by importing each of its modules."""
    for module in pkgutil.iter_modules(ops_contracts.__path__):
        importlib.import_module(f"ops_contracts.{module.name}")
    found: list[type[ServiceShape]] = []
    todo = list(ServiceShape.__subclasses__())
    while todo:
        shape = todo.pop()
        found.append(shape)
        todo += shape.__subclasses__()
    return sorted(found, key=lambda m: m.__name__)


def _described(schema: dict[str, Any]) -> tuple[str, list[str], object]:
    """What a reader depends on in an object schema: each property's type, which are always sent, and whether an
    unknown field is refused. A nested model is named the same in both documents, whichever section holds it, and a
    field's default is left out: every field is sent, and a service's document does not print it."""
    listed: dict[str, dict[str, Any]] = schema.get("properties", {})
    typed = {name: {k: v for k, v in field.items() if k != "default"} for name, field in listed.items()}
    properties = json.dumps(typed, sort_keys=True).replace("#/$defs/", "#/components/schemas/")
    required: list[str] = schema.get("required", [])
    return properties, sorted(required), schema.get("additionalProperties")


def shape_differences(services: Path, shapes: list[type[ServiceShape]]) -> tuple[set[str], set[str]]:
    """(findings, `<service>: <shape>` for each document that carries a shape as the contract describes it). A
    finding is a document whose component of a shape's name differs from the contract, or whose component of another
    name holds every field the shape needs: the same shape declared a second time."""
    found: set[str] = set()
    carried: set[str] = set()
    for path in sorted(services.glob("*/openapi.json")):
        service = path.parent.name
        components: dict[str, dict[str, Any]] = json.loads(path.read_text()).get("components", {}).get("schemas", {})
        for shape in shapes:
            name = shape.__name__
            contract = shape.model_json_schema(mode="serialization", by_alias=True)
            needed: set[str] = set(shape.model_json_schema(mode="validation", by_alias=True).get("required", []))
            for component, schema in components.items():
                fields: set[str] = set(schema.get("properties", {}))
                if component == name:
                    if _described(schema) == _described(contract):
                        carried.add(f"{service}: {name}")
                    else:
                        named: set[str] = set(contract["properties"])
                        apart = sorted(fields ^ named) or ["the same fields, typed differently"]
                        found.add(f"{service}: {name} differs from ops_contracts ({', '.join(apart)})")
                elif needed and needed <= fields:
                    found.add(f"{service}: {component} declares ops_contracts' {name} again")
    return found, carried


def test_the_scan_finds_a_shape_two_services_describe_differently(tmp_path: Path) -> None:
    (shape,) = [s for s in service_shapes() if s.__name__ == "CopyRef"]
    sent = shape.model_json_schema(mode="serialization", by_alias=True)
    # The reader's own copy of the shape, one field behind the sender's, and the sender's under its own name.
    behind = {**sent, "properties": {k: v for k, v in sent["properties"].items() if k != "detachedAt"}}
    for service, components in (
        ("agents-service", {"CopyRef": sent}),
        ("tools-service", {"CopyRef": behind}),
        ("documents-service", {"TeamCopy": sent}),
    ):
        (tmp_path / service).mkdir()
        (tmp_path / service / "openapi.json").write_text(json.dumps({"components": {"schemas": components}}))
    found, carried = shape_differences(tmp_path, [shape])
    assert found == {
        "tools-service: CopyRef differs from ops_contracts (detachedAt)",
        "documents-service: TeamCopy declares ops_contracts' CopyRef again",
    }
    assert carried == {"agents-service: CopyRef"}


def test_services_describe_a_shared_shape_as_its_contract_does() -> None:
    shapes = service_shapes()
    found, carried = shape_differences(ROOT / "services", shapes)
    assert len(list((ROOT / "services").glob("*/openapi.json"))) >= 6, "the scan reads too few documents"
    assert found == set(), "a shape services send each other is declared outside ops_contracts:\n" + "\n".join(
        sorted(found)
    )
    unused = {s.__name__ for s in shapes} - {c.split(": ")[1] for c in carried}
    assert shapes and not unused, (
        f"no service's document carries {sorted(unused) or 'any shape'}; the scan compares nothing"
    )
