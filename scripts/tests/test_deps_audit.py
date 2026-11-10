"""The dependency gate: every advisory is reported, and only a critical one outside the baseline fails the run."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def load() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("deps_audit", SCRIPTS / "deps_audit.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["deps_audit"] = module
    spec.loader.exec_module(module)
    return module


def osv_doc(name: str, version: str, ids: list[str], score: str) -> dict:
    """Return osv-scanner JSON holding one package with one advisory group."""
    package = {"name": name, "version": version, "ecosystem": "npm"}
    return {"results": [{"packages": [{"package": package, "groups": [{"ids": ids, "max_severity": score}]}]}]}


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    module = load()
    baseline = tmp_path / "audit-baseline.txt"
    baseline.write_text("GHSA-known-0001  left in place by the owner\n")
    monkeypatch.setattr(module, "BASELINE", baseline)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.delenv("OSSINDEX_TOKEN", raising=False)
    return module


def test_critical_advisory_outside_the_baseline_fails(audit: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "run_osv", lambda: osv_doc("minimist", "1.2.5", ["GHSA-xvch-5gv4-984h"], "9.8"))
    assert audit.cmd_vulns() == 1


def test_baselined_critical_advisory_passes(audit: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "run_osv", lambda: osv_doc("left-pad", "1.0.0", ["GHSA-known-0001"], "9.1"))
    assert audit.cmd_vulns() == 0


def test_advisory_below_critical_is_listed_and_passes(
    audit: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(audit, "run_osv", lambda: osv_doc("lodash", "4.17.15", ["GHSA-p6mc-m468-83gw"], "7.4"))
    assert audit.cmd_vulns() == 0
    assert "GHSA-p6mc-m468-83gw" in capsys.readouterr().out


def test_oss_index_critical_finding_fails(audit: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "pyyaml"\nversion = "5.3"\nsource = { registry = "https://pypi.org/simple" }\n'
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n\npackages:\n\nsnapshots:\n")
    monkeypatch.setenv("OSSINDEX_TOKEN", "token")
    monkeypatch.setenv("OSSINDEX_USER", "ci@example.test")
    report = [{"coordinates": "pkg:pypi/pyyaml@5.3", "vulnerabilities": [{"cve": "CVE-2020-1747", "cvssScore": 9.8}]}]
    monkeypatch.setattr(audit.urllib.request, "urlopen", lambda req, timeout: io.BytesIO(json.dumps(report).encode()))
    monkeypatch.setattr(audit, "run_osv", lambda: {"results": []})
    assert audit.cmd_vulns() == 1
