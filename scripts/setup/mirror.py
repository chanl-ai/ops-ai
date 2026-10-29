"""The mirror answers: a PyPI index, an npm registry and a container registry, or none. Each package mirror must
serve the file the lockfile pins for one known package, through scripts/deps_doctor.py's own checks, so an index that
answers while it blocks pinned files fails here (the case deps-doctor exists for). The registry must answer `/v2/`.
The URLs are written with their credentials (D3), and no line shows them."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

import deps_doctor
from deps_doctor import NpmRegistry, PyIndex, Registry, read_pnpm_lock, read_uv_lock, split_credentials

from setup.report import Result

NONE = ("", "none", "no")
PYPI_PROBE, NPM_PROBE = "httpx", "next"
TIMEOUT_S = 20


def _secrets(url: str) -> tuple[str, ...]:
    parts = urllib.parse.urlsplit(url)
    return tuple(s for s in (parts.password, urllib.parse.unquote(parts.password or "")) if s)


def pypi(url: str) -> Result:
    item = "pypi mirror"
    if url.strip().lower() in NONE:
        return Result(item, True, "none: packages come from pypi.org", answer=url)
    pkg = next((p for p in read_uv_lock(deps_doctor.ROOT / "uv.lock") if p.name == PYPI_PROBE), None)
    if pkg is None:
        return Result(item, False, f"{PYPI_PROBE} is not in uv.lock to probe with", answer=url)
    row = PyIndex(Registry.from_url(url)).check(pkg)
    secrets = _secrets(url)
    if row.status != 200:
        why = row.note or f"the pinned file answered {row.status}"
        return Result(item, False, f"{pkg.name} {pkg.version}: {why}", secrets=secrets, answer=url)
    return Result(item, True, f"serves {pkg.name} {pkg.version}", {"UV_DEFAULT_INDEX": url}, secrets, url)


def npm(url: str) -> Result:
    item = "npm mirror"
    if url.strip().lower() in NONE:
        return Result(item, True, "none: packages come from registry.npmjs.org", answer=url)
    version = next((v for n, v in read_pnpm_lock(deps_doctor.ROOT / "pnpm-lock.yaml") if n == NPM_PROBE), None)
    if version is None:
        return Result(item, False, f"{NPM_PROBE} is not in pnpm-lock.yaml to probe with", answer=url)
    row = NpmRegistry(Registry.from_url(url)).check(NPM_PROBE, version)
    secrets = _secrets(url)
    if row.status != 200:
        why = row.note or f"the pinned tarball answered {row.status}"
        return Result(item, False, f"{NPM_PROBE} {version}: {why}", secrets=secrets, answer=url)
    return Result(item, True, f"serves {NPM_PROBE} {version}", {"NPM_CONFIG_REGISTRY": url}, secrets, url)


def registry(prefix: str) -> Result:
    """`prefix` is what image names are put behind (OPS_BASE_IMAGE_PREFIX, `registry.example/dockerhub/`); its host
    must answer the registry API's `/v2/`. A 401 that names the API means it is there and pulls need `docker login`."""
    item = "container registry"
    if prefix.strip().lower() in NONE:
        return Result(item, True, "none: images come from Docker Hub", answer=prefix)
    raw = prefix if "://" in prefix else f"https://{prefix}"
    clean, auth = split_credentials(raw)
    parts = urllib.parse.urlsplit(clean)
    secrets = _secrets(raw)
    request = urllib.request.Request(
        f"{parts.scheme}://{parts.netloc}/v2/", headers={"Authorization": auth} if auth else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as r:
            status, headers = r.status, r.headers
    except urllib.error.HTTPError as e:
        status, headers = e.code, e.headers
    except (urllib.error.URLError, OSError) as e:
        return Result(item, False, f"{parts.netloc}: {e}", secrets=secrets, answer=prefix)
    value = f"{parts.netloc}{parts.path.rstrip('/')}/"
    if status == 200:
        return Result(item, True, f"{parts.netloc} answers /v2/", {"OPS_BASE_IMAGE_PREFIX": value}, secrets, prefix)
    if status == 401 and headers.get("Docker-Distribution-API-Version"):
        reason = f"{parts.netloc} answers /v2/; pulls need `docker login {parts.netloc}`"
        return Result(item, True, reason, {"OPS_BASE_IMAGE_PREFIX": value}, secrets, prefix)
    return Result(item, False, f"{parts.netloc}/v2/ answered {status}, not a registry", secrets=secrets, answer=prefix)
