"""A thread's knowledge bases are named as kb-service named them when it was opened (c-170), by failure mode: a thread
saved before names were kept showing the agents seed's names, which can differ from kb-service's."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agents.api.chat_threads import thread_base


def seeded_name(_kb_id: str) -> str:
    return "Fraud & payments"


def test_an_older_thread_without_saved_names_shows_ids_not_seed_names() -> None:
    rt: Any = SimpleNamespace(catalog=SimpleNamespace(kb_name=seeded_name))
    row = {"id": "th_1", "meta": {"agentId": "ag_fraud", "kbIds": ["kb_people"]}, "created_at": "now"}
    assert thread_base(rt, row, [])["kb_names"] == ["kb_people"]
    saved = {**row, "meta": {"agentId": "ag_fraud", "kbIds": ["kb_people"], "kbNames": ["People policies"]}}
    assert thread_base(rt, saved, [])["kb_names"] == ["People policies"]
