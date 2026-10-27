"""Known vulnerabilities and copyleft licences in the lockfiles; the audit half of `make qa-mirror`.

  deps_audit.py vulns      osv-scanner on uv.lock and pnpm-lock.yaml (the binary, or its container image), plus
                           Sonatype OSS Index when OSSINDEX_TOKEN is set. A critical advisory (CVSS 9.0 or higher)
                           that deploy/mirror-test/audit-baseline.txt does not list fails the run.
  deps_audit.py age        every locked version is at least 30 days old: Python from the upload times uv.lock
                           records, npm from the registry named by NPM_CONFIG_REGISTRY. A younger one that
                           deploy/mirror-test/audit-baseline.txt does not name fails the run.
  deps_audit.py licenses   the licence of every installed Python distribution and every npm package; an AGPL or GPL
                           licence that deploy/mirror-test/audit-baseline.txt does not list fails the run. LGPL and
                           weaker licences are reported, not failed. Run it after `uv sync` and `pnpm install`.

The baseline file holds one `<ID or package>  <reason>` per line: an advisory or licence the owner has seen and left
in place. Lines that no longer match anything are reported so the file does not collect dead entries.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "deploy" / "mirror-test" / "audit-baseline.txt"
OSV_IMAGE = os.environ.get("OPS_OSV_IMAGE", "ghcr.io/google/osv-scanner:v2.7.0")
CRITICAL = 9.0
OSSINDEX_URL = "https://ossindex.sonatype.org/api/v3/component-report"
STRONG_COPYLEFT = re.compile(r"\bAGPL|(?<![A-Za-z])GPL|GNU (Affero )?General Public", re.IGNORECASE)
WEAK = re.compile(r"LGPL|Lesser", re.IGNORECASE)

sys.path.insert(0, str(Path(__file__).parent))
from deps_doctor import NpmRegistry, Registry, read_pnpm_lock  # noqa: E402  # one registry reader for doctor and audit
from sbom import licence_of  # noqa: E402  # one licence reader for the dependency table and this audit


def read_baseline() -> dict[str, str]:
    entries: dict[str, str] = {}
    if BASELINE.exists():
        for raw in BASELINE.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                key, _, reason = line.partition(" ")
                entries[key] = reason.strip()
    return entries


ADVISORY_ID = re.compile(r"^(GHSA|PYSEC|CVE|OSV)-")


def report_unused(baseline: dict[str, str], used: set[str], advisories: bool) -> None:
    """Names the baseline lines of this kind (advisory ids or licence package names) that matched nothing."""
    for key in sorted(k for k in set(baseline) - used if bool(ADVISORY_ID.match(k)) == advisories):
        print(f"  baseline entry matches nothing now and can be removed: {key}")


# --- vulnerabilities --------------------------------------------------------------------------------------------


def run_osv() -> dict:
    lockfiles = [ROOT / "uv.lock", ROOT / "pnpm-lock.yaml"]
    if shutil.which("osv-scanner"):
        cmd = ["osv-scanner", "scan", "source", *[a for f in lockfiles for a in ("-L", str(f))], "--format", "json"]
    elif shutil.which("docker"):
        # Copies of the two lockfiles only, so the container sees no source tree.
        work = Path(tempfile.mkdtemp(prefix="ops-osv-"))
        for f in lockfiles:
            shutil.copy(f, work / f.name)
        cmd = ["docker", "run", "--rm", "-v", f"{work}:/src:ro", OSV_IMAGE, "scan", "source"]
        cmd += [a for f in lockfiles for a in ("-L", f"/src/{f.name}")] + ["--format", "json"]
    else:
        sys.exit("vulns: neither osv-scanner nor docker is installed")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if not proc.stdout.strip():
        sys.exit(f"vulns: osv-scanner printed nothing (exit {proc.returncode}): {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def osv_findings(doc: dict) -> list[dict]:
    found = []
    for result in doc.get("results", []):
        for pkg in result.get("packages", []):
            info = pkg["package"]
            for group in pkg.get("groups", []):
                try:
                    score = float(group.get("max_severity") or 0)
                except ValueError:
                    score = 0.0
                found.append(
                    {
                        "ecosystem": info["ecosystem"],
                        "name": info["name"],
                        "version": info["version"],
                        "ids": group.get("ids", []),
                        "score": score,
                    }
                )
    return found


def ossindex_findings() -> list[dict]:
    token, user = os.environ.get("OSSINDEX_TOKEN"), os.environ.get("OSSINDEX_USER")
    if not token:
        print("OSS Index: skipped (OSSINDEX_TOKEN is not set)")
        return []
    if not user:
        sys.exit(
            "OSS Index: OSSINDEX_TOKEN is set but OSSINDEX_USER (the account's email) is not; it is the Basic login"
        )
    purls = []
    lock = ROOT / "uv.lock"
    for pkg in tomllib.loads(lock.read_text()).get("package", []):
        if "registry" in pkg.get("source", {}):
            purls.append(f"pkg:pypi/{pkg['name']}@{pkg['version']}")
    for line in (
        (ROOT / "pnpm-lock.yaml").read_text().split("\npackages:\n", 1)[-1].split("\nsnapshots:\n")[0].splitlines()
    ):
        m = re.match(r"^  '?((?:@[^/\s']+/)?[^@\s']+)@([^\s':(]+)'?:\s*$", line)
        if m:
            name = m.group(1).replace("@", "%40", 1) if m.group(1).startswith("@") else m.group(1)
            purls.append(f"pkg:npm/{name}@{m.group(2)}")
    found = []
    auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
    for i in range(0, len(purls), 128):
        req = urllib.request.Request(
            OSSINDEX_URL,
            data=json.dumps({"coordinates": purls[i : i + 128]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": auth},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                reports = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            sys.exit(f"OSS Index answered {exc.code}")
        for rep in reports:
            for vuln in rep.get("vulnerabilities", []):
                found.append(
                    {
                        "ecosystem": "OSSIndex",
                        "name": rep["coordinates"],
                        "version": "",
                        "ids": [vuln.get("cve") or vuln.get("displayName") or vuln.get("id")],
                        "score": float(vuln.get("cvssScore") or 0),
                    }
                )
    return found


def cmd_vulns() -> int:
    baseline = read_baseline()
    findings = osv_findings(run_osv()) + ossindex_findings()
    critical = [f for f in findings if f["score"] >= CRITICAL]
    used: set[str] = set()
    failing = []
    print(f"vulnerabilities: {len(findings)} advisories, {len(critical)} critical (CVSS {CRITICAL} or higher)")
    for f in sorted(critical, key=lambda f: (f["ecosystem"], f["name"], -f["score"])):
        known = next((i for i in f["ids"] if i in baseline), None)
        if known:
            used.add(known)
        else:
            failing.append(f)
        state = f"baselined: {baseline[known]}" if known else "NEW"
        print(f"  {f['score']:>4} {f['ecosystem']} {f['name']} {f['version']} {', '.join(f['ids'][:2])}  [{state}]")
    report_unused(baseline, used, advisories=True)
    if failing:
        print(f"FAIL: {len(failing)} critical advisories are not in {BASELINE.relative_to(ROOT)}")
        return 1
    print("vulnerabilities: PASS (every critical advisory is listed in the baseline)")
    return 0


# --- age ---------------------------------------------------------------------------------------------------------


def python_ages(now: datetime) -> list[tuple[str, str, datetime]]:
    """(name, version, oldest upload time of the version's files) for each registry package in uv.lock."""
    out = []
    for pkg in tomllib.loads((ROOT / "uv.lock").read_text()).get("package", []):
        if "registry" not in pkg.get("source", {}):
            continue
        files = [*pkg.get("wheels", []), *([pkg["sdist"]] if "sdist" in pkg else [])]
        times = [f["upload-time"] for f in files if f.get("upload-time")]
        if times:
            out.append(
                (
                    pkg["name"],
                    pkg["version"],
                    min(t if isinstance(t, datetime) else datetime.fromisoformat(t) for t in times),
                )
            )
    return out


def npm_ages() -> list[tuple[str, str, datetime]]:
    registry = NpmRegistry(Registry.from_url(os.environ.get("NPM_CONFIG_REGISTRY") or "https://registry.npmjs.org"))
    out = []
    for name, version in read_pnpm_lock(ROOT / "pnpm-lock.yaml"):
        status, doc = registry.packument(name)
        stamp = doc.get("time", {}).get(version) if status == 200 else None
        if stamp:
            out.append((name, version, datetime.fromisoformat(stamp.replace("Z", "+00:00"))))
        else:
            print(f"  age unknown for npm {name} {version} (registry answered {status}, no publish time)")
    return out


def cmd_age(min_days: int) -> int:
    baseline = read_baseline()
    now = datetime.now(UTC)
    rows = [("pypi", *r) for r in python_ages(now)] + [("npm", *r) for r in npm_ages()]
    used: set[str] = set()
    failing = []
    for eco, name, version, published in rows:
        stamp = published if published.tzinfo else published.replace(tzinfo=UTC)
        days = (now - stamp).days
        if days >= min_days:
            continue
        if name in baseline:
            used.add(name)
            print(f"  {eco} {name} {version}: {days} days old  [baselined: {baseline[name]}]")
        else:
            failing.append((eco, name, version, days))
            print(f"  {eco} {name} {version}: {days} days old  [NEW]")
    print(f"age: {len(rows)} locked versions checked against {min_days} days")
    report_unused(baseline, used, advisories=False)
    if failing:
        print(f"FAIL: {len(failing)} versions are younger than {min_days} days and not in {BASELINE.relative_to(ROOT)}")
        return 1
    print("age: PASS")
    return 0


# --- licences ---------------------------------------------------------------------------------------------------


def strong_copyleft(expression: str) -> bool:
    """True when every way of reading the licence expression is strong copyleft (`MIT OR GPL-3.0` is a choice)."""
    alternatives = re.split(r"\s+OR\s+|\s*/\s*|\s*\|\s*", expression)
    return all(STRONG_COPYLEFT.search(a) and not WEAK.search(a) for a in alternatives)


def python_licences() -> list[tuple[str, str, str]]:
    return sorted(
        {(d.metadata["Name"], d.version, licence_of(d)) for d in metadata.distributions() if d.metadata["Name"]}
    )


def npm_licences() -> list[tuple[str, str, str]]:
    proc = subprocess.run(["pnpm", "licenses", "list", "--json"], cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        sys.exit(f"licenses: pnpm licenses list failed: {proc.stderr[-400:]}")
    out = []
    for lic, pkgs in json.loads(proc.stdout).items():
        for p in pkgs:
            for v in p.get("versions", [""]):
                out.append((p["name"], v, lic))
    return sorted(out)


def cmd_licenses() -> int:
    baseline = read_baseline()
    rows = [("pypi", *r) for r in python_licences()] + [("npm", *r) for r in npm_licences()]
    used: set[str] = set()
    failing = []
    weak = [r for r in rows if WEAK.search(r[3])]
    print(f"licences: {len(rows)} packages checked, {len(weak)} weak copyleft (LGPL), reported only")
    for eco, name, version, lic in rows:
        if not strong_copyleft(lic):
            continue
        key = f"{name}"
        if key in baseline:
            used.add(key)
            print(f"  {eco} {name} {version}: {lic}  [baselined: {baseline[key]}]")
        else:
            failing.append((eco, name, version, lic))
            print(f"  {eco} {name} {version}: {lic}  [NEW]")
    report_unused(baseline, used, advisories=False)
    if failing:
        print(f"FAIL: {len(failing)} AGPL or GPL packages are not in {BASELINE.relative_to(ROOT)}")
        return 1
    print("licences: PASS (no AGPL or GPL package outside the baseline)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=["vulns", "licenses", "age"])
    ap.add_argument("--min-days", type=int, default=30)
    args = ap.parse_args()
    return {"vulns": cmd_vulns, "licenses": cmd_licenses, "age": lambda: cmd_age(args.min_days)}[args.what]()


if __name__ == "__main__":
    sys.exit(main())
