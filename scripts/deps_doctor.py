"""`make deps-doctor`: asks the package mirror whether it serves every version the lockfiles pin.

Run it on the developer's machine with the mirror's settings in the environment (UV_DEFAULT_INDEX for Python,
NPM_CONFIG_REGISTRY for npm; docs/deploy/install.md, "Behind a company mirror"). For each locked package it prints the
name, the locked version, the HTTP status of that version's file on the mirror, and the newest version the mirror
does serve. Packages the mirror blocks go into `.mirror/constraints.txt` (Python, pip syntax) and
`.mirror/npm-overrides.json`, which `make deps-relock MIRROR=1` locks within.

Credentials in a registry URL are masked in every line this prints. The standard library only, so it runs before any
dependency is installed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

try:
    from packaging.version import Version
except ImportError:  # the doctor runs before any dependency is installed
    Version = None

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYPI = "https://pypi.org/simple"
DEFAULT_NPM = "https://registry.npmjs.org"
TIMEOUT = 60
RETRIES = 2
PROBES = 8  # a blocked package is probed on up to 4 times this many other versions
_SECRETS: set[str] = set()


def mask(text: str) -> str:
    """Hides `user:password@` in a URL and any credential value learnt from one, in anything printed."""
    text = re.sub(r"(?<=://)[^/@\s]+:[^/@\s]*@", "***@", str(text))
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return text


def split_credentials(url: str) -> tuple[str, str | None]:
    """The URL without credentials, and the Basic header value for them (None when the URL carries none)."""
    parts = urllib.parse.urlsplit(url)
    if not parts.username:
        return url, None
    user, password = urllib.parse.unquote(parts.username), urllib.parse.unquote(parts.password or "")
    _SECRETS.update(s for s in (parts.password, password, user) if s and len(s) > 3)
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    clean = urllib.parse.urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return clean, "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@dataclass
class Registry:
    base: str
    auth: str | None = None

    @classmethod
    def from_url(cls, url: str) -> Registry:
        clean, auth = split_credentials(url.strip())
        return cls(clean.rstrip("/"), auth)

    def request(self, url: str, method: str = "GET", accept: str | None = None) -> tuple[int, bytes]:
        clean, url_auth = split_credentials(url)
        headers = {"User-Agent": "ops-ai-deps-doctor"}
        if accept:
            headers["Accept"] = accept
        # Credentials go to the mirror's own host only, never to a redirect target such as an object store.
        if (self.auth or url_auth) and urllib.parse.urlsplit(clean).netloc == urllib.parse.urlsplit(self.base).netloc:
            headers["Authorization"] = url_auth or self.auth or ""
        req = urllib.request.Request(clean, method=method, headers=headers)
        status, body = 0, b""
        for attempt in range(RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    return resp.status, (resp.read() if method == "GET" else b"")
            except urllib.error.HTTPError as exc:
                status, body = exc.code, b""
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                status, body = 0, mask(getattr(exc, "reason", exc)).encode()
            # A mirror fetching a package for the first time answers slowly or with a 5xx; a 4xx is its real answer.
            if status and status < 500:
                break
            time.sleep(1 + attempt)
        return status, body


# --- versions ---------------------------------------------------------------------------------------------------


def version_key(version: str) -> tuple:
    if Version is not None:
        try:
            parsed = Version(version)
            return (0 if parsed.is_prerelease else 1, parsed)
        except ValueError:
            pass
    return (1, tuple(int(n) for n in re.findall(r"\d+", version)))


def newest_first(versions: set[str]) -> list[str]:
    stable = [v for v in versions if re.fullmatch(r"\d+(\.\d+)*([.-]?post\d+)?", v)]
    pool = stable or list(versions)
    return sorted(pool, key=version_key, reverse=True)


def fallbacks(versions: set[str], locked: str) -> list[str]:
    """Other versions to try when the locked one is blocked: older ones, newest first, then newer ones."""
    ordered = newest_first(versions - {locked})
    cut = version_key(locked)
    try:
        older = [v for v in ordered if version_key(v) < cut]
    except TypeError:
        older = []
    return (older + [v for v in ordered if v not in older])[: PROBES * 4]


# --- Python -----------------------------------------------------------------------------------------------------


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def filename_version(filename: str, name: str) -> str | None:
    base = filename
    for suffix in (".tar.gz", ".zip", ".tar.bz2", ".tar.xz"):
        if base.endswith(suffix):
            stem = base[: -len(suffix)]
            m = re.match(r"(?P<n>.+?)-(?P<v>\d[^-]*)$", stem)
            return m.group("v") if m and normalize(m.group("n")) == normalize(name) else None
    if base.endswith(".whl"):
        parts = base[:-4].split("-")
        return parts[1] if len(parts) >= 5 and normalize(parts[0]) == normalize(name) else None
    return None


@dataclass
class PyPackage:
    name: str
    version: str
    files: list[str]  # file names the lock records for this version


@dataclass
class Row:
    ecosystem: str
    name: str
    locked: str
    status: int
    served: str = ""
    note: str = ""
    newest: str = ""


def read_uv_lock(path: Path) -> list[PyPackage]:
    lock = tomllib.loads(path.read_text())
    out: list[PyPackage] = []
    for pkg in lock.get("package", []):
        if "registry" not in pkg.get("source", {}) or "version" not in pkg:
            continue
        names = [Path(urllib.parse.urlsplit(w["url"]).path).name for w in pkg.get("wheels", []) if "url" in w]
        sdist = pkg.get("sdist", {})
        if sdist.get("url"):
            names.append(Path(urllib.parse.urlsplit(sdist["url"]).path).name)
        out.append(PyPackage(pkg["name"], pkg["version"], names))
    return out


def preferred_file(files: list[str]) -> str | None:
    """The file this machine would install: a pure-Python wheel, else a wheel for its platform, else the sdist."""
    system = {"darwin": "macosx", "linux": "manylinux", "win32": "win"}.get(sys.platform, "")
    machine = platform.machine().lower()

    def score(f: str) -> int:
        if f.endswith("-none-any.whl"):
            return 4
        if f.endswith(".whl") and "cp312" in f and system in f and machine in f:
            return 3
        if f.endswith(".whl") and "abi3" in f and system in f and machine in f:
            return 3
        if not f.endswith(".whl"):
            return 2
        return 1

    return max(files, key=score) if files else None


class PyIndex:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def page(self, name: str) -> tuple[int, dict[str, str]]:
        """Status of the package's page and {file name: absolute URL} for every file it lists."""
        url = f"{self.registry.base}/{normalize(name)}/"
        status, body = self.registry.request(url, accept="text/html")
        if status != 200:
            return status, {}
        parser = _Links()
        parser.feed(body.decode("utf-8", "replace"))
        files = {}
        for href in parser.hrefs:
            absolute = urllib.parse.urljoin(url, href.split("#")[0])
            files[Path(urllib.parse.urlsplit(absolute).path).name] = absolute
        return 200, files

    def check(self, pkg: PyPackage) -> Row:
        row = Row("pypi", pkg.name, pkg.version, 0)
        status, listing = self.page(pkg.name)
        if status != 200:
            row.status = status
            row.note = "no page for this package" if status == 404 else "the mirror refused the package page"
            return row
        by_version: dict[str, list[str]] = {}
        for fname in listing:
            v = filename_version(fname, pkg.name)
            if v:
                by_version.setdefault(v, []).append(fname)
        row.newest = (newest_first(set(by_version)) or [""])[0]
        wanted = preferred_file([f for f in pkg.files if f in listing])
        wanted = wanted or preferred_file(by_version.get(pkg.version, []))
        if not wanted:
            row.status = 404
            row.note = "the mirror does not list this version"
        else:
            row.status = self.registry.request(listing[wanted], method="HEAD")[0]
        if row.status == 200:
            row.served = pkg.version
            return row
        for candidate in fallbacks(set(by_version), pkg.version):
            file = preferred_file(by_version[candidate])
            if file and self.registry.request(listing[file], method="HEAD")[0] == 200:
                row.served = candidate
                break
        return row


# --- npm ---------------------------------------------------------------------------------------------------------


def read_pnpm_lock(path: Path) -> list[tuple[str, str]]:
    text = path.read_text()
    section = text.split("\npackages:\n", 1)[1].split("\nsnapshots:\n", 1)[0] if "\npackages:\n" in text else ""
    seen: list[tuple[str, str]] = []
    for m in re.finditer(r"^  '?(?P<key>(?:@[^/\s']+/)?[^@\s']+@[^\s':(]+)'?:\s*$", section, re.M):
        name, version = m.group("key").rsplit("@", 1)
        seen.append((name, version))
    return sorted(set(seen))


class NpmRegistry:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._packuments: dict[str, tuple[int, dict]] = {}

    def packument(self, name: str) -> tuple[int, dict]:
        if name not in self._packuments:
            url = f"{self.registry.base}/{urllib.parse.quote(name, safe='@').replace('/', '%2F')}"
            status, body = self.registry.request(url, accept="application/vnd.npm.install-v1+json, application/json")
            doc: dict = {}
            if status == 200:
                try:
                    doc = json.loads(body)
                except ValueError:
                    status = 502
            self._packuments[name] = (status, doc)
        return self._packuments[name]

    def tarball(self, name: str, doc: dict, version: str) -> str | None:
        info = doc.get("versions", {}).get(version)
        if info and info.get("dist", {}).get("tarball"):
            return info["dist"]["tarball"]
        return None

    def check(self, name: str, version: str) -> Row:
        row = Row("npm", name, version, 0)
        status, doc = self.packument(name)
        if status != 200:
            row.status = status
            row.note = "no page for this package" if status == 404 else "the mirror refused the package page"
            return row
        versions = set(doc.get("versions", {}))
        row.newest = (newest_first(versions) or [""])[0]
        url = self.tarball(name, doc, version)
        if not url:
            row.status, row.note = 404, "the mirror does not list this version"
        else:
            row.status = self.registry.request(url, method="HEAD")[0]
        if row.status == 200:
            row.served = version
            return row
        for candidate in fallbacks(versions, version):
            url = self.tarball(name, doc, candidate)
            if url and self.registry.request(url, method="HEAD")[0] == 200:
                row.served = candidate
                break
        return row


# --- run ---------------------------------------------------------------------------------------------------------


def env_registry(names: tuple[str, ...], default: str) -> str:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    return default


def render(rows: list[Row], only_problems: bool) -> str:
    shown = [r for r in rows if r.status != 200] if only_problems else rows
    if not shown:
        return "no rows"
    width = max(7, *(len(r.name) for r in shown)) + 2
    lines = [f"{'package':<{width}}{'eco':<5}{'locked':<16}{'status':<10}newest the mirror serves"]
    for r in shown:
        status = str(r.status) if r.status else "no reply"
        served = r.served or "none found"
        extra = f"  ({r.note})" if r.note and r.status != 200 else ""
        lines.append(f"{r.name:<{width}}{r.ecosystem:<5}{r.locked:<16}{status:<10}{served}{extra}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pypi-index", default=env_registry(("UV_DEFAULT_INDEX", "UV_INDEX_URL"), DEFAULT_PYPI))
    ap.add_argument("--npm-registry", default=env_registry(("NPM_CONFIG_REGISTRY", "npm_config_registry"), DEFAULT_NPM))
    ap.add_argument("--uv-lock", type=Path, default=ROOT / "uv.lock")
    ap.add_argument("--pnpm-lock", type=Path, default=ROOT / "pnpm-lock.yaml")
    ap.add_argument("--out", type=Path, default=ROOT / ".mirror")
    ap.add_argument("--all", action="store_true", help="print every package, not only the blocked ones")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    py_registry, npm_registry = Registry.from_url(args.pypi_index), Registry.from_url(args.npm_registry)
    print(f"Python index  {mask(py_registry.base)}\nnpm registry  {mask(npm_registry.base)}")
    py = PyIndex(py_registry)
    npm = NpmRegistry(npm_registry)
    py_pkgs = read_uv_lock(args.uv_lock)
    npm_pkgs = read_pnpm_lock(args.pnpm_lock)
    with ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(py.check, py_pkgs)) + list(pool.map(lambda p: npm.check(*p), npm_pkgs))

    blocked = [r for r in rows if r.status != 200]
    n_py = len([r for r in rows if r.ecosystem == "pypi"])
    print(
        f"\nChecked {n_py} Python and {len(rows) - n_py} npm packages: {len(blocked)} not served at the locked one.\n"
    )
    if blocked or args.all:
        print(render(rows, only_problems=not args.all))

    args.out.mkdir(exist_ok=True)
    constraints = [f"{r.name}=={r.served}" for r in blocked if r.ecosystem == "pypi" and r.served]
    overrides = {r.name: r.served for r in blocked if r.ecosystem == "npm" and r.served}
    (args.out / "constraints.txt").write_text("\n".join(sorted(constraints)) + ("\n" if constraints else ""))
    (args.out / "npm-overrides.json").write_text(json.dumps(dict(sorted(overrides.items())), indent=2) + "\n")
    if blocked:
        none_served = [r.name for r in blocked if not r.served]
        print(f"\nWrote {len(constraints)} Python constraints to {args.out}/constraints.txt")
        print(f"and {len(overrides)} npm overrides to {args.out}/npm-overrides.json.")
        if none_served:
            print(f"No served version at all for: {', '.join(none_served)}. Ask the mirror's owner to allow one.")
        print("Next: make deps-relock MIRROR=1")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
