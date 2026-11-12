"""The stack a use case page runs against (packages/usecase-runner/src/page.ts). Starts the services the page's Details
row names on the run's ports and database, writes a saved sign-in file with one profile per person on the page, prints
READY, and stops everything when the runner closes stdin. The page's code reads that file through OPS_CONFIG, as it
would read a developer's own profile."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

from usecase_harness import ROOT, fake_openai, kb, models

RERANK_RULES = ROOT / "services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--profiles", required=True)
    ap.add_argument("--services", default="")
    ns = ap.parse_args()
    services: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="usecase-page-") as tmp, ExitStack() as stack:
        # Pages say which services in words; knowledge brings its files and documents services with it.
        if "knowledge" in ns.services:
            env = None
            if "scripted chat model" in ns.services:
                # Rerank and rewrite call a chat model; the fake answers their prompts from the fixture, so no provider is called.
                fake = stack.enter_context(fake_openai(RERANK_RULES))
                models_url = stack.enter_context(models({"OPS_MODELS_FAKE_OPENAI_URL": fake}))
                env = {"OPS_MODELS_URL": models_url, "OPS_MODELS_KEY": "mk_dev_kb"}
            services["kb"] = str(stack.enter_context(kb(Path(tmp) / "files", env=env)).base_url).rstrip("/")
        if not services:
            raise SystemExit(f"page_stack starts the knowledge services only; the page asks for: {ns.services!r}")
        profile = {"baseUrl": "http://127.0.0.1", "team": "team_ops", "services": services}
        names = ns.profiles.split(",")
        Path(ns.config).write_text(json.dumps({"profiles": dict.fromkeys(names, profile), "current": names[0]}))
        print("READY", flush=True)
        sys.stdin.read()


main()
