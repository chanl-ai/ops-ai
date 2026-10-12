"""Writes docs/architecture/dependencies.md: every package in the Runtime's lock with version, licence, direct or
transitive, native code, network behaviour and why it is there. Run with `make sbom` after any lock change.

Versions come from `uv export --frozen`; licences and native-code detection from the installed distributions'
metadata, so run it after `make install`. Network behaviour and reasons are reviewed by hand in NOTES below; a
package without a note is reported as transitive, required by its parents in the lock.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
ROOT = SERVICE.parents[1]
OUT = ROOT / "docs" / "architecture" / "dependencies.md"
# Every workspace member whose dependencies ship in a deployed image.
MEMBERS = [*ROOT.glob("packages/*/pyproject.toml"), *ROOT.glob("services/*-service/pyproject.toml")]
# Classifiers spell licences out ("GNU Lesser General Public License") or version them ("GPLv3"), which the bare
# acronyms miss: `\b` does not fall between "GPL" and "v3".
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|SSPL|EUPL|OSL|L?GPLv\d|GNU (Affero |Lesser )?General Public)\b", re.IGNORECASE)
NATIVE_SUFFIXES = {".so", ".pyd", ".dylib", ".dll"}
WEAK_COPYLEFT = re.compile(r"\b(MPL|EPL|CDDL)\b", re.IGNORECASE)
# Platform-specific wheels not installed on the machine that generates this file; licence read from PyPI by hand.
LICENCE_OVERRIDES = {
    "colorama": "BSD-3-Clause (PyPI classifier; Windows only)",
    "httpx2-jsfetch": "BSD-3-Clause (PyPI; Pyodide only)",
}

# name: (makes network calls on its own, why we need it). "Only when called" means the code makes no call unless the
# Runtime asks it to, e.g. an HTTP client.
NOTES: dict[str, tuple[str, str]] = {
    "pydantic-ai-slim": (
        "No. Prints a start-up banner with a Logfire URL to stdout (text only);"
        " `make run` sets PYDANTIC_AI_NO_BANNER=1",
        "Agent loop (ADR-0014). Installed with the `openai` and `anthropic` extras; no logfire",
    ),
    "pydantic-graph": ("No", "Graph engine Pydantic AI runs its loop on"),
    "anthropic": (
        "Only when called: HTTPS to api.anthropic.com, and only when the model alias is a claude-* model",
        "Optional provider SDK (Anthropic), used when OPS_MODEL_ALIAS names a Claude model",
    ),
    "openai": ("Only when called: HTTPS to api.openai.com for each model request", "Chat model provider SDK (gpt-5.5)"),
    "tiktoken": (
        "Yes: on first use downloads its BPE encoding file from openaipublic.blob.core.windows.net. Mitigation: vendor"
        " the encoding file into the image and set TIKTOKEN_CACHE_DIR to it, so no download happens at run time",
        "Token counting for OpenAI models, required by pydantic-ai-slim[openai]",
    ),
    "requests": ("Only when called (by tiktoken's encoding download)", "HTTP client tiktoken uses to fetch encodings"),
    "regex": ("No", "Tokeniser patterns for tiktoken"),
    "jiter": ("No", "Fast JSON parser the OpenAI and Anthropic SDKs use"),
    "genai-prices": (
        "No by default. `pydantic_ai.prices.update_in_background()` would fetch prices from raw.githubusercontent.com;"
        " the Runtime never calls it",
        "Token price table Pydantic AI uses for usage cost",
    ),
    "logfire-api": (
        "No. A no-op shim unless the `logfire` package is installed, and it is not",
        "Instrumentation hooks Pydantic AI calls; inert here",
    ),
    "opentelemetry-api": ("No. API only; no SDK or exporter is installed", "Tracing API Pydantic AI and FastAPI call"),
    "griffelib": ("No", "Reads tool docstrings for Pydantic AI tool descriptions"),
    "fastapi": ("No", "HTTP API framework (spec 17 section 3)"),
    "starlette": ("No", "ASGI toolkit under FastAPI"),
    "uvicorn": ("No outbound calls; serves the API", "ASGI server"),
    "sse-starlette": ("No", "Server-sent events for the chat reply stream"),
    "sqlalchemy": (
        "Only when called: connects to the configured PostgreSQL",
        "SQL toolkit (Core, no ORM) for the chat tables",
    ),
    "alembic": ("Only when run: connects to the configured PostgreSQL", "Schema migrations"),
    "asyncpg": (
        "Only when called: connects to the configured PostgreSQL",
        "PostgreSQL driver for the chat tables and the checkpointer (Apache-2.0, chosen over LGPL psycopg)",
    ),
    "pydantic": ("No", "Contract models and validation"),
    "pydantic-core": ("No", "Compiled validation core of Pydantic"),
    "pydantic-settings": ("No", "The one Settings object read from the environment at boot"),
    "python-dotenv": (
        "No. Reads a .env file only when one is configured; the Runtime configures none"
        " (the environment supplies the values)",
        "Optional .env loader of pydantic-settings and uvicorn; unused",
    ),
    "httpx": (
        "Only when called",
        "HTTP client; used by tests and scripts/prove-chat.py, and by the Anthropic SDK path",
    ),
    "httpx2": ("Only when called", "HTTP client the Anthropic SDK and genai-prices use"),
    "httpcore": ("Only when called", "Transport under httpx"),
    "httpcore2": ("Only when called", "Transport under httpx2"),
    "truststore": ("No. Reads the operating system's certificate store", "TLS trust from the OS store for httpx2"),
    "certifi": ("No", "Mozilla CA bundle for TLS"),
    "aiosqlite": ("No", "SQLite driver for the API tests' in-memory database (dev)"),
    "pytest": ("No", "Test runner (dev)"),
    "pytest-asyncio": ("No", "Async tests (dev)"),
    "ruff": ("No", "Lint and format (dev)"),
    "pyright": (
        "Yes, dev only: on first run downloads Node.js and the pyright npm package through nodeenv",
        "Strict type checker (dev)",
    ),
    "nodeenv": ("Yes, dev only: downloads Node.js when pyright asks for it", "Node installer pyright uses (dev)"),
    "uvloop": ("No", "Faster event loop for uvicorn"),
    "httptools": ("No", "Faster HTTP parser for uvicorn"),
    "watchfiles": ("No", "File watching for uvicorn reload (dev convenience)"),
    "websockets": ("No outbound calls", "WebSocket support in uvicorn[standard]; unused by the Runtime"),
    "greenlet": ("No", "Async bridge SQLAlchemy needs for asyncio"),
    "langgraph": ("No", "Graph runtime: nodes, edges, Send fan-out, interrupt and resume, checkpointed state"),
    "langgraph-checkpoint": ("No", "Checkpointer interface and serialiser LangGraph saves state through"),
    "langgraph-checkpoint-conformance": (
        "No",
        "LangGraph's checkpointer conformance suite, run against ops-checkpointer in tests/checkpointer",
    ),
    "langgraph-prebuilt": ("No", "Prebuilt nodes LangGraph imports; unused by the Runtime's graphs"),
    "langgraph-sdk": (
        "Only when called; the Runtime never calls it",
        "LangGraph Server client LangGraph imports; unused",
    ),
    "langchain-core": ("No", "Runnable config and callbacks LangGraph is built on"),
    "langchain-protocol": ("No", "Message protocol types langchain-core imports"),
    "langsmith": (
        "Off by default: sends traces to LangSmith only when LANGSMITH_TRACING is true and an API key is set; neither"
        " is set in the development environment, and a deployment must not set them",
        "Tracing client langchain-core imports; inert here",
    ),
    "ormsgpack": ("No", "Serialises checkpoints"),
    "orjson": ("No", "Fast JSON for langsmith and langgraph"),
    "xxhash": ("No", "Hashing for LangGraph's channel versions"),
    "zstandard": ("No", "Compression langsmith imports"),
    "tenacity": ("No", "Retry helper langchain-core imports"),
    "jsonpatch": ("No", "JSON patch support langchain-core imports"),
}


@dataclass
class Row:
    name: str
    version: str
    licence: str
    kind: str
    native: str
    network: str
    why: str
    flags: list[str]


def export(*args: str) -> str:
    return subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--no-emit-workspace", "--no-header", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def parse(text: str) -> dict[str, tuple[str, list[str]]]:
    """name -> (version, parents), from requirements output with `# via` annotations."""
    out: dict[str, tuple[str, list[str]]] = {}
    current = ""
    for line in text.splitlines():
        if m := re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", line):
            current = m.group(1).lower()
            out[current] = (m.group(2), [])
        elif current and (v := re.match(r"^\s+#\s+(?:via\s+)?([A-Za-z0-9_.\-]+)", line)) and v.group(1) != "via":
            out[current][1].append(v.group(1).lower())
    return out


def normalise(req: str) -> str:
    return re.split(r"[\[<>=!~ ;]", req, maxsplit=1)[0].lower().replace("_", "-")


def declared() -> tuple[set[str], set[str]]:
    runtime: set[str] = set()
    for pyproject in MEMBERS:
        runtime |= {normalise(d) for d in tomllib.loads(pyproject.read_text())["project"]["dependencies"]}
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = {normalise(d) for d in root["dependency-groups"]["dev"]}
    return {d for d in runtime if not d.startswith("ops-")}, dev


def licence_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata.json
    expr = meta.get("license_expression")
    if isinstance(expr, str) and expr:
        return expr
    raw = meta.get("classifier", [])
    classifiers = [
        c.split("::")[-1].strip() for c in ([raw] if isinstance(raw, str) else raw) if c.startswith("License ::")
    ]
    lic = meta.get("license", "")
    text = (lic if isinstance(lic, str) else "").strip()
    if text and len(text) <= 60 and "\n" not in text:
        return text
    return ", ".join(classifiers) or (text.splitlines()[0][:60] if text else "unknown")


def native_of(dist: metadata.Distribution) -> bool:
    wheel = dist.read_text("WHEEL") or ""
    if "Root-Is-Purelib: false" in wheel:
        return True
    return any(Path(str(f)).suffix in NATIVE_SUFFIXES for f in dist.files or [])


def build() -> list[Row]:
    locked = parse(export())
    runtime_set = set(parse(export("--no-dev")))
    direct_runtime, direct_dev = declared()
    rows: list[Row] = []
    for name, (version, parents) in sorted(locked.items()):
        try:
            dist = metadata.distribution(name)
            licence, native = licence_of(dist), native_of(dist)
        except metadata.PackageNotFoundError:
            licence, native = LICENCE_OVERRIDES.get(name, "not installed on this platform"), False
        dev_only = name not in runtime_set
        if name in direct_runtime:
            kind = "direct"
        elif name in direct_dev:
            kind = "direct (dev)"
        else:
            kind = "transitive (dev)" if dev_only else "transitive"
        network, why = NOTES.get(name, ("No", ""))
        if not why:
            via = ", ".join(p for p in parents if not p.startswith("ops-")) or "the workspace"
            why = f"Required by {via}"
        flags: list[str] = []
        if COPYLEFT.search(licence):
            flags.append("copyleft licence")
        elif WEAK_COPYLEFT.search(licence):
            flags.append("weak copyleft (file-level)")
        if licence in {"unknown", "not installed on this platform"}:
            flags.append("licence not confirmed")
        if native:
            flags.append("native code")
        if network.startswith(("Yes", "Off by default")) or "would fetch" in network:
            flags.append("network")
        rows.append(Row(name, version, licence, kind, "yes" if native else "no", network, why, flags))
    return rows


def render(rows: list[Row]) -> str:
    flagged = [r for r in rows if r.flags]
    lines = [
        "# Runtime dependencies",
        "",
        "Status: current. Generated by `make -C services/agents-service sbom` on"
        f" {datetime.now(UTC).date().isoformat()} from",
        "`uv.lock`. Do not edit by hand; change the lock or the notes in `services/agents-service/scripts/sbom.py`"
        " and regenerate.",
        "",
        f"{len(rows)} packages: {sum(r.kind == 'direct' for r in rows)} direct runtime,"
        f" {sum(r.kind == 'transitive' for r in rows)} transitive runtime,"
        f" {sum('dev' in r.kind for r in rows)} dev only"
        " (not in the deployed image).",
        "",
        "Chat runs on OpenAI (gpt-5.5) per the owner's ruling of 2026-10-10, so Pydantic AI is installed as"
        " `pydantic-ai-slim[openai,anthropic]` with no `logfire`. Restriction note: the `openai` extra brings"
        " `tiktoken`, which downloads encoding files from a public blob store"
        " the first time it is used. For a deployment with no outbound internet, vendor the encoding file into"
        " the image and set TIKTOKEN_CACHE_DIR to it. The LangGraph checkpointer is the workspace's own"
        " ops-checkpointer on asyncpg, so no LGPL PostgreSQL driver is installed.",
        "",
        "## Flagged",
        "",
        "| Package | Version | Licence | Native | Network | Why flagged |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r.name} | {r.version} | {r.licence} | {r.native} | {r.network} | {', '.join(r.flags)} |"
            for r in flagged
        ],
        "",
        "## All packages",
        "",
        "| Package | Version | Licence | Direct or transitive | Native code | Network calls on its own"
        " | Why we need it |",
        "|---|---|---|---|---|---|---|",
        *[f"| {r.name} | {r.version} | {r.licence} | {r.kind} | {r.native} | {r.network} | {r.why} |" for r in rows],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    rows = build()
    OUT.write_text(render(rows))
    sys.stdout.write(f"sbom: {len(rows)} packages, {sum(bool(r.flags) for r in rows)} flagged -> {OUT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
