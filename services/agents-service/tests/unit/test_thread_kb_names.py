"""A thread's knowledge bases are named as kb-service named them when it was opened, by failure mode: a thread
saved before names were kept showing the agents seed's names, which can differ from kb-service's."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agents.api.chat_threads import thread_base
from ops_agents.store.graphs import StoredThread
from ops_service_kit.http import Json


def thread(meta: Json) -> StoredThread:
    return StoredThread.model_validate(
        {"id": "th_1", "graph": "agent_wrapper", "meta": meta, "team_id": "t", "created_at": "now", "updated_at": "now",
         "status": "idle", "version": None, "digest": None, "external_key": None, "deployment_id": None,
         "parent_thread_id": None, "overrides": None, "owner": None, "tenant_id": "local"}
    )  # fmt: skip


def seeded_name(_kb_id: str) -> str:
    return "Fraud & payments"


def test_an_older_thread_without_saved_names_shows_ids_not_seed_names() -> None:
    rt: Any = SimpleNamespace(catalog=SimpleNamespace(kb_name=seeded_name))
    row = thread({"agentId": "ag_fraud", "kbIds": ["kb_people"]})
    assert thread_base(rt, row, [])["kb_names"] == ["kb_people"]
    saved = thread({"agentId": "ag_fraud", "kbIds": ["kb_people"], "kbNames": ["People policies"]})
    assert thread_base(rt, saved, [])["kb_names"] == ["People policies"]
