"""The `ops` areas that drive the console's routes, by failure mode: a person named by first name signs in as someone
else or not at all; a kept session from another stack is sent and refused; a chat reply's stream, tool calls or
Connect card are lost on the way to the terminal; a widget action reaches the wrong widget or with the wrong body;
a file meant for a knowledge base is uploaded under another purpose or never added; an invite goes out without
--send; a model test spends money without --confirm; models calls miss models-service; and the same bytes uploaded
for a second purpose are refused under the first upload's key."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from ops_ai import OpsAI
from ops_ai._cli import chat_script, common
from ops_ai._client import _upload_meta
from ops_ai.cli import main

ROOT = next(p for p in Path(__file__).resolve().parents if (p / common.SEED / "people.json").is_file())


def _client(seen: list[httpx.Request], answer: Any) -> OpsAI:
    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return answer(r)

    return OpsAI(
        api_key="ok_t",
        base_url="https://ops.test",
        team="team_a",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _ok(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def _use(monkeypatch: pytest.MonkeyPatch, module: str, ops: OpsAI) -> None:
    monkeypatch.setattr(f"ops_ai._cli.{module}.client", lambda _ns: ops)


def test_as_takes_a_seeded_persons_first_name_and_lists_the_names_when_none_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(ROOT)
    assert common.dev_email("james") == "j.richardson@harborpine.example"
    assert common.dev_email("viewer") == "r.menon@harborpine.example"
    with pytest.raises(ValueError, match="nadia"):
        common.dev_email("nobody")


def test_a_kept_session_from_another_stack_is_not_sent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("OPS_API_TOKENS", str(tmp_path))
    monkeypatch.setenv("OPS_PLATFORM_PORT", "8710")
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    kept = {"email": "j.richardson@harborpine.example", "team": "team_ops", "token": "old", "expiresAt": later}
    (tmp_path / "local-j.richardson_harborpine.example.json").write_text(
        json.dumps({**kept, "platform": "http://127.0.0.1:9999"})
    )
    signed: list[str] = []

    def sign_in(_base: str, _services: dict[str, str], email: str, _password: str) -> dict[str, Any]:
        signed.append(email)
        principal = {"email": email, "teamId": "team_ops"}
        return {"token": "new", "refreshToken": "r", "expiresAt": later, "principal": principal}

    monkeypatch.setattr(common, "sign_in", sign_in)
    ns = argparse.Namespace(as_role="james", base_url=None, team=None)
    assert common.dev_sign_in(ns)[2]["token"] == "new"
    assert signed == ["j.richardson@harborpine.example"]
    # The session it kept is this stack's, so the next command signs in no more.
    assert common.dev_sign_in(ns)[2]["token"] == "new"
    assert signed == ["j.richardson@harborpine.example"]


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events)


def test_chat_say_streams_the_reply_and_prints_the_connect_card(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = {
        "name": "salesforce_query",
        "status": "failed",
        "input": {"q": "SELECT Id FROM Case"},
        "output": {
            "error": {
                "code": "CONNECTION_NOT_LINKED",
                "message": "Connect Salesforce first",
                "details": {"connection": "Salesforce", "connectUrl": "https://sf.example/authorize?x=1"},
            }
        },
    }
    stream = _sse(
        {"type": "status", "phase": "thinking"},
        {"type": "tool_end", "call": refused},
        {"type": "text", "delta": "Please "},
        {"type": "text", "delta": "connect."},
    )

    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/messages"):
            return httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"})
        if r.url.path.endswith("/v1/executions"):
            return _ok({"data": []})
        return _ok({"id": "th_1"}, 201)

    seen: list[httpx.Request] = []
    _use(monkeypatch, "chat", _client(seen, answer))
    assert main(["chat", "say", "-m", "Status of case 42?"]) == 0
    out = capsys.readouterr().out
    send = next(r for r in seen if r.url.path.endswith("/messages"))
    assert send.url.path == "/api/agents/v1/chat/threads/th_1/messages"
    assert json.loads(send.content) == {"content": "Status of case 42?"}
    assert send.headers["accept"] == "text/event-stream"
    assert "CARD Connect Salesforce" in out and "https://sf.example/authorize?x=1" in out
    assert "agent > Please connect." in out


def test_chat_approve_acts_on_the_newest_open_widget(monkeypatch: pytest.MonkeyPatch) -> None:
    thread = {
        "id": "th_1",
        "messages": [
            {"id": "m1", "widgets": [{"id": "w_old", "kind": "approval", "state": "approved"}]},
            {"id": "m2", "widgets": [{"id": "w_new", "kind": "approval", "state": "pending"}]},
        ],
    }

    def answer(r: httpx.Request) -> httpx.Response:
        return _ok({"id": "w_new", "state": "approved"}) if r.method == "POST" else _ok(thread)

    seen: list[httpx.Request] = []
    _use(monkeypatch, "chat", _client(seen, answer))
    assert main(["chat", "approve", "th_1", "--json"]) == 0
    assert seen[-1].url.path == "/api/agents/v1/chat/threads/th_1/messages/m2/widgets/w_new/actions"
    assert json.loads(seen[-1].content) == {"type": "approve"}
    assert main(["chat", "submit", "th_1", "w_new", "--value", "amount=40", "--json"]) == 0
    assert json.loads(seen[-1].content) == {"type": "submit", "values": {"amount": "40"}}


def test_chat_script_fails_a_turn_whose_card_was_not_shown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/messages"):
            return httpx.Response(200, content=_sse({"type": "text", "delta": "Done."}))
        return _ok({"id": "th_1"}, 201)

    script = tmp_path / "s.json"
    script.write_text(json.dumps({"turns": [{"say": "Status?", "expect": {"card": True}}]}))
    _use(monkeypatch, "chat", _client([], answer))
    assert main(["chat", "script", str(script)]) == 1
    assert "FAIL Connect card shown" in capsys.readouterr().out


def test_kb_add_file_uploads_for_knowledge_and_adds_it_to_the_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/uploads"):
            return _ok({"fileId": "fil_1"}, 201)
        if r.url.path.endswith("/complete"):
            return _ok({"file": {"id": "fil_1"}})
        return _ok({"sourceId": "src_1", "files": [{"fileId": "fil_1"}]})

    seen: list[httpx.Request] = []
    _use(monkeypatch, "kb", _client(seen, answer))
    page = tmp_path / "fees.md"
    page.write_text("An overdraft fee applies.")
    assert main(["kb", "add-file", "kb_1", str(page), "--json"]) == 0
    ticket = json.loads(next(r for r in seen if r.url.path.endswith("/uploads")).content)
    assert ticket["purpose"] == "knowledge_source" and ticket["name"] == "fees.md"
    assert seen[-1].url.path == "/api/kb/v1/knowledge-bases/kb_1/documents"
    assert json.loads(seen[-1].content) == {"fileIds": ["fil_1"]}


def test_people_invite_sends_nothing_without_send(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    _use(monkeypatch, "people", _client(seen, lambda _r: _ok({"invited": 1})))
    assert main(["people", "invite", "a@bank.example", "--role", "viewer", "--json"]) == 0
    assert seen == []
    assert main(["people", "invite", "a@bank.example", "--role", "viewer", "--send", "--json"]) == 0
    assert seen[-1].url.path == "/api/platform/v1/settings/members/invite"
    assert json.loads(seen[-1].content) == {"emails": ["a@bank.example"], "role": "viewer"}


def test_models_test_spends_nothing_without_confirm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[httpx.Request] = []
    _use(monkeypatch, "people", _client(seen, lambda _r: _ok([])))
    assert main(["models", "test", "Ops Assistant"]) == 2
    assert seen == [] and "--confirm" in capsys.readouterr().err


def test_models_keys_go_to_models_service(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    _use(monkeypatch, "people", _client(seen, lambda _r: _ok([{"name": "openai"}])))
    assert main(["models", "keys", "--json"]) == 0
    assert seen[-1].url.path == "/api/models/v1/provider-keys"


def test_the_same_bytes_for_another_purpose_are_another_upload() -> None:
    _, first = _upload_meta("notice.pdf", b"%PDF", "application/pdf", "knowledge_source")
    _, again = _upload_meta("notice.pdf", b"%PDF", "application/pdf", "knowledge_source")
    _, other = _upload_meta("notice.pdf", b"%PDF", "application/pdf", "case_attachment")
    assert first == again and first != other


def _fake_sign_in(signed: list[str]) -> Any:
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))

    def sign_in(_base: str, _services: dict[str, str], email: str, _password: str) -> dict[str, Any]:
        signed.append(email)
        return {"token": "t", "refreshToken": "r", "expiresAt": later, "principal": {"email": email}}

    return sign_in


def test_ops_login_as_signs_in_afresh_so_the_profile_can_renew(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("OPS_API_TOKENS", str(tmp_path))
    monkeypatch.setenv("OPS_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("OPS_PLATFORM_PORT", "8710")
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    # `make api` keeps a session with no refresh token.
    kept = {"email": "p.shah@harborpine.example", "token": "k", "expiresAt": later, "platform": "http://127.0.0.1:8710"}
    (tmp_path / "local-admin.json").write_text(json.dumps(kept))
    signed: list[str] = []
    monkeypatch.setattr(common, "sign_in", _fake_sign_in(signed))
    assert main(["login", "--as", "admin", "--quiet"]) == 0
    assert signed == ["p.shah@harborpine.example"]
    assert json.loads((tmp_path / "config.json").read_text())["profiles"]["default"]["refreshToken"] == "r"


def test_as_an_email_outside_the_repo_signs_in_without_a_kept_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPS_API_TOKENS", raising=False)
    signed: list[str] = []
    monkeypatch.setattr(common, "sign_in", _fake_sign_in(signed))
    ns = argparse.Namespace(as_role="dev@bank.example", base_url="http://127.0.0.1:8710", team=None)
    assert common.dev_sign_in(ns)[2]["token"] == "t"
    assert signed == ["dev@bank.example"]


def test_models_test_runs_on_a_test_thread_that_remembers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith(("/v1/agents", "/v1/chat/agents")):
            return _ok({"data": [{"id": "ag_1", "name": "Ops Assistant"}]})
        if r.url.path.endswith("/messages"):
            return httpx.Response(200, content=_sse({"type": "text", "delta": "4"}))
        return _ok({"id": "th_t"}, 201)

    seen: list[httpx.Request] = []
    _use(monkeypatch, "people", _client(seen, answer))
    assert main(["models", "test", "Ops Assistant", "--confirm", "--quiet"]) == 0
    made = next(r for r in seen if r.method == "POST" and r.url.path.endswith("/v1/chat/threads"))
    # A test thread is the agent page's Test panel: kept out of the person's memory and their chat list.
    assert json.loads(made.content) == {"kbIds": [], "agentId": "ag_1", "test": True}


def test_test_data_clean_never_touches_unmarked_or_another_persons_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    chats = [{"id": "th_real", "title": "Quarterly numbers"}, {"id": "th_t", "title": "[test] Status?"}]
    tests = [{"id": "th_tt", "title": "[test] What is 2 + 2?"}, {"id": "th_panel", "title": "Try the new prompt"}]
    files = [
        {"id": "fil_m", "name": "[test] note.txt", "uploadedBy": "j.richardson@harborpine.example"},
        {"id": "fil_o", "name": "[test] note.txt", "uploadedBy": "p.shah@harborpine.example"},
        {"id": "fil_u", "name": "contract [test].pdf", "uploadedBy": "j.richardson@harborpine.example"},
    ]

    def answer(r: httpx.Request) -> httpx.Response:
        if r.method == "DELETE":
            return httpx.Response(204)
        if r.url.path.endswith("/v1/chat/threads"):
            return _ok({"items": tests if r.url.params.get("test") == "true" else chats})
        return _ok({"data": files})

    seen: list[httpx.Request] = []
    monkeypatch.setattr("ops_ai._cli.testdata.person_client", lambda _ns, _who: _client(seen, answer))
    assert main(["test-data", "clean", "--people", "james", "--json"]) == 0
    assert not [r for r in seen if r.method == "DELETE"]
    assert main(["test-data", "clean", "--people", "james", "--confirm", "--json"]) == 0
    removed = sorted(r.url.path.rsplit("/", 1)[-1] for r in seen if r.method == "DELETE")
    assert removed == ["fil_m", "th_t", "th_tt"]


def test_a_chat_started_as_a_seed_person_carries_the_test_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/messages"):
            return httpx.Response(200, content=_sse({"type": "text", "delta": "ok"}))
        if r.url.path.endswith("/v1/executions"):
            return _ok({"data": []})
        return _ok({"id": "th_1"}, 201)

    seen: list[httpx.Request] = []
    _use(monkeypatch, "chat", _client(seen, answer))
    assert main(["chat", "say", "-m", "Status of case 42?", "--as", "james", "--quiet"]) == 0
    made = next(r for r in seen if r.url.path.endswith("/v1/chat/threads"))
    assert json.loads(made.content)["title"] == "[test] Status of case 42?"


def _seen(text: str, tools: list[str] | None = None) -> dict[str, Any]:
    return {"text": text, "tools": [{"name": t} for t in tools or []], "cards": [], "error": None}


def _failed(want: dict[str, Any], text: str, message: dict[str, Any] | None = None) -> list[str]:
    return [name for name, ok, _ in chat_script.reply_checks(want, _seen(text), message or {}) if not ok]


def test_the_assistant_expectations_each_catch_their_failure() -> None:
    # One reply per failure the assistant's scripts guard against, and a clean reply that passes them all.
    assert _failed({"noQuestion": True}, "I found two cases. Want me to show the team's tasks?") == [
        "asks nothing back"
    ]
    assert _failed({"noErrorCode": True}, "Error: CONNECTION_NOT_LINKED, connect first.") == ["no error code"]
    assert _failed({"endsClean": True}, "Two cases are open.\n\nok") == ["ends clean"]
    assert _failed({"endsClean": True}, "It stays open until the review is done.") == []
    assert _failed({"endsClean": True}, "It is escalated, from \u201cControl testing.\u201d") == []
    assert _failed({"cites": True}, "Overdue reviews are escalated.", {"citations": []}) == ["cites the knowledge"]
    assert _failed({"table": True}, "Three are waiting.", {"parts": []}) == ["draws a table"]
    assert _failed({"maxSteps": 2}, "Done.", {"usage": {"calls": 5}}) == ["at most 2 steps"]
    clean = {"citations": [{"n": 1}], "parts": [{"shape": "rows"}], "usage": {"calls": 2}}
    want = {"noQuestion": True, "noErrorCode": True, "endsClean": True, "cites": True, "table": True, "maxSteps": 2}
    assert _failed(want, "Customer CUS-1002 waits on its tax return [1].", clean) == []
    # Knowledge the assistant read with search_knowledge is cited by the document it came from.
    searched = _seen("Per Control testing, reviews escalate.", [])
    searched["tools"] = [{"name": "search_knowledge", "output": {"passages": [{"title": "Control testing"}]}}]
    assert all(ok for _, ok, _ in chat_script.reply_checks({"cites": True}, searched, {}))
    searched["tools"][0]["output"]["passages"][0]["knowledgeBase"] = "Risk policies"
    searched["text"] = "Per the Risk policies, reviews escalate."
    assert all(ok for _, ok, _ in chat_script.reply_checks({"cites": True}, searched, {}))
    searched["text"] = "Reviews escalate."
    assert not any(ok for _, ok, _ in chat_script.reply_checks({"cites": True}, searched, {}))


def test_chat_script_reads_the_stored_reply_for_its_steps(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # maxSteps is read from the reply the chat stored, not the stream, which carries no model call count.
    stored = {"id": "th_1", "messages": [{"role": "assistant", "content": "Two cases.", "usage": {"calls": 4}}]}

    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/messages"):
            return httpx.Response(200, content=_sse({"type": "text", "delta": "Two cases."}))
        if r.method == "GET" and r.url.path.endswith("/threads/th_1"):
            return _ok(stored)
        return _ok({"id": "th_1"}, 201)

    script = tmp_path / "s.json"
    script.write_text(json.dumps({"turns": [{"say": "Cases?", "expect": {"maxSteps": 3}}]}))
    _use(monkeypatch, "chat", _client([], answer))
    assert main(["chat", "script", str(script)]) == 1
    assert "FAIL at most 3 steps: 4 model calls" in capsys.readouterr().out


def test_evals_run_each_script_as_its_people_and_keep_the_real_subset_within_its_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    ran: list[tuple[str, str]] = []

    def run(ns: argparse.Namespace, _ops: Any, path: Path) -> chat_script.Outcome:
        ran.append((path.stem, ns.as_role))
        return chat_script.Outcome(True, 3, "th_x")

    monkeypatch.setattr(chat_script, "run_script", run)
    monkeypatch.setattr(chat_script, "client", lambda _ns: None)
    turns = [{"say": "x", "expect": {"maxSteps": 3}}]
    (tmp_path / "a.yaml").write_text(json.dumps({"as": ["wealth", "risk"], "real": ["wealth"], "turns": turns}))
    (tmp_path / "b.yaml").write_text(json.dumps({"as": ["lending"], "real": ["lending", "risk"], "turns": turns}))
    assert main(["chat", "evals", str(tmp_path)]) == 0
    assert ran == [("a", "wealth"), ("a", "risk"), ("b", "lending")]
    ran.clear()
    # Three real runs of three calls each would pass a cap of 8: the third is skipped, and the run fails.
    assert main(["chat", "evals", str(tmp_path), "--real", "--max-calls", "8"]) == 1
    assert ran == [("a", "wealth"), ("b", "lending")]
    assert "SKIP" in capsys.readouterr().out
