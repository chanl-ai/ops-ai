"""No service depends on another service's code (c-189): services talk over their APIs through
`ops_identity.ServiceClient` and share code only through packages/. By failure mode: an import of another service's
package coming back in source or tests; a service call written by hand (its own token minting next to a raw HTTP
client) instead of through ServiceClient; and a scan that finds nothing because it reads nothing (first run on a file
that breaks it)."""

from __future__ import annotations

import ast
from pathlib import Path

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
# What remains to move (c-189 T006: the tool catalog leaves agents-service; the gateway tests move to tools-service).
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
    "services/tools-service/tests/test_tenants_kept_apart.py: ops_agents",
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
# ops_identity is the mark of a call to another service written by hand. None is left (c-189); keep it that way.
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


# Reading a document is documents-service's job (c-256): the workflow runner and the agent kernel ask it through
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
