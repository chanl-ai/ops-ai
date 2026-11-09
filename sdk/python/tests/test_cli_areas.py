"""The `opsai` areas that drive the console's routes, by failure mode: a person named by first name signs in as someone
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
from ops_ai._cli.transcript import transcript
from ops_ai._client import _upload_meta
from ops_ai.cli import main
from ops_ai.errors import NotFound

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


def test_chat_script_signs_out_first_and_restores_the_sign_in_between_turns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A script that needs a sign-in waited for a person at a browser; `signedOut` and `connected: restore` remove and
    put back the kept sign-in (make sf-signin-remove / -restore), in order, and the follow-up goes to the thread."""
    steps: list[str] = []
    monkeypatch.setattr(chat_script, "sign_in_step", lambda _ns, action: steps.append(action))
    said: list[str] = []

    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/messages"):
            said.append(json.loads(r.content).get("content", ""))
            return httpx.Response(200, content=_sse({"type": "text", "delta": "Done."}))
        return _ok({"id": "th_1"}, 201)

    script = tmp_path / "s.json"
    turns = [{"say": "List my accounts"}, {"connected": "restore"}]
    script.write_text(json.dumps({"signedOut": True, "turns": turns}))
    _use(monkeypatch, "chat", _client([], answer))
    main(["chat", "script", str(script)])
    assert steps == ["remove", "restore"], steps
    assert said[0] == "List my accounts" and len(said) == 2, said


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


def test_a_kept_session_with_no_refresh_token_is_signed_in_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # make api keeps a session with no refresh token; reused, a role change answered permissions_changed with no way to
    # renew until the file was deleted by hand.
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("OPS_API_TOKENS", str(tmp_path))
    monkeypatch.setenv("OPS_PLATFORM_PORT", "8710")
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    kept = {"email": "j.richardson@harborpine.example", "team": "team_ops", "token": "old", "expiresAt": later}
    (tmp_path / "local-j.richardson_harborpine.example.json").write_text(
        json.dumps({**kept, "platform": "http://127.0.0.1:8710"})
    )

    def sign_in(_base: str, _services: dict[str, str], email: str, _password: str) -> dict[str, Any]:
        return {"token": "new", "refreshToken": "r", "expiresAt": later, "principal": {"email": email}}

    monkeypatch.setattr(common, "sign_in", sign_in)
    session = common.dev_sign_in(argparse.Namespace(as_role="james", base_url=None, team=None))[2]
    assert (session["token"], session["refreshToken"]) == ("new", "r")


def test_a_sign_in_nobody_answers_names_the_address_and_how_to_reach_the_stack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Run outside make, the CLI signed in at the fallback address and printed only "not_found: Not Found".
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("OPS_API_TOKENS", str(tmp_path))
    for v in common.SERVICE_PORTS.values():
        monkeypatch.delenv(v, raising=False)
    monkeypatch.delenv("OPS_BASE_URL", raising=False)

    def sign_in(*_: Any) -> dict[str, Any]:
        raise NotFound(404, "not_found", "Not Found")

    monkeypatch.setattr(common, "sign_in", sign_in)
    with pytest.raises(ValueError, match=r"http://127\.0\.0\.1:8710.*make"):
        common.dev_sign_in(argparse.Namespace(as_role="james", base_url=None, team=None))


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


def _thread(*turns: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for say, reply in turns:
        messages += [{"role": "user", "content": say}, {"role": "assistant", "model": "default", **reply}]
    return {"id": "th_1", "title": "[test] Cases", "agentName": "Ops Assistant", "messages": messages}


def _transcript(thread: dict[str, Any], log: list[dict[str, Any]] | None = None, *, every: bool = False) -> str:
    return transcript(thread, person="James Richardson", team="Operations", log=log or [], all_turns=every)


def test_a_refused_call_is_marked_refused_with_the_app_to_connect() -> None:
    refused = {
        "name": "salesforce_query",
        "label": "Run a SOQL query",
        "status": "failed",
        "input": {"q": "SELECT Id FROM Case"},
        "output": {"error": {"code": "CONNECTION_NOT_LINKED", "details": {"connection": "Salesforce"}}},
    }
    denied = {"name": "send_email", "label": "Send an email", "status": "failed", "input": {"to": "a@b.example"}}
    log = [{"target": "send_email", "decision": "deny", "reason": "egress host not allowed", "at": "1"}]
    text = _transcript(_thread(("Status?", {"content": "Connect first.", "toolCalls": [refused, denied]})), log)
    assert "Run a SOQL query (q SELECT Id FROM Case) → refused: connect Salesforce first" in text
    assert "Send an email (to a@b.example) → refused: egress host not allowed" in text
    assert "{" not in text


def test_a_card_and_a_table_are_one_line_each_with_their_row_count() -> None:
    parts = [
        {"type": "widget", "shape": "rows", "hint": {"title": "Cases"}, "data": [{"id": "c1"}, {"id": "c2"}]},
        {"type": "card", "title": "Customer", "children": [{"type": "text", "text": "x"}]},
    ]
    text = _transcript(_thread(("Show cases", {"content": "Here.", "parts": parts})))
    assert "- table: Cases (2 rows)" in text
    assert "- card: Customer" in text
    assert "c1" not in text


def test_multi_turn_shows_the_last_turn_unless_all_turns_and_wraps_on_words(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    long = "word " * 60 + "https://bank.example/" + "a" * 110
    thread = _thread(
        ("First question", {"content": "First answer", "usage": {"calls": 1, "seconds": 2.0}}),
        ("Second question", {"content": long, "usage": {"calls": 2, "seconds": 3.5}}),
    )

    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/v1/me"):
            return _ok({"user": {"name": "James Richardson"}, "teams": [{"id": "team_a", "name": "Operations"}]})
        if r.url.path.endswith("/v1/executions"):
            return _ok({"data": []})
        return _ok(thread)

    _use(monkeypatch, "chat", _client([], answer))
    assert main(["chat", "transcript", "--thread", "th_1"]) == 0
    last = capsys.readouterr().out
    assert "Second question" in last and "First question" not in last
    assert "James Richardson (Operations) with Ops Assistant on `default` · turn 2: 2 model calls, 0 tool calls" in last
    body = last.splitlines()[2:]
    assert all(len(line) <= 100 or " " not in line for line in body)
    assert "https://bank.example/" + "a" * 110 in last
    assert main(["chat", "transcript", "--thread", "th_1", "--all-turns"]) == 0
    every = capsys.readouterr().out
    assert every.index("First question") < every.index("Second question")
    assert "turn 1: 1 model call, 0 tool calls, 2.0 s; turn 2" in every


def test_apps_on_turns_the_app_on_as_the_window_does_and_prints_the_sign_in_link(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    card = {"id": "plugin:opsai.salesforce", "name": "Salesforce", "toolsAdded": 9, "connectionId": "ca_1"}
    card["moduleIds"] = ["mod_plugin_salesforce"]

    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/team"):
            return _ok(card)
        if r.url.path.endswith("/team-assistant/app-tools"):
            return _ok(
                {"agentId": "ag_ops", "agentName": "Ops Assistant", "tools": ["salesforce_query"], "state": "given"}
            )
        if r.url.path.endswith("/sign-in"):
            return _ok({"authorizeUrl": "https://sf.example/authorize?x=1", "redirectUri": "https://c/return"})
        return _ok({"card": card, "accounts": []})

    seen: list[httpx.Request] = []
    _use(monkeypatch, "apps", _client(seen, answer))
    place = "https://acme.my.salesforce.com/services/oauth2"
    assert main(["apps", "on", "plugin:opsai.salesforce", "--place", place]) == 0
    out = capsys.readouterr().out
    turned = next(r for r in seen if r.url.path.endswith("/team"))
    assert json.loads(turned.content) == {"enabled": True, "signIn": "person_or_team", "settings": {"login_url": place}}
    gave = next(r for r in seen if r.url.path.endswith("/team-assistant/app-tools"))
    assert json.loads(gave.content) == {"moduleIds": ["mod_plugin_salesforce"]}
    signed = next(r for r in seen if r.url.path.endswith("/sign-in"))
    assert json.loads(signed.content) == {"account": "team"}
    assert "9 read tools added" in out and "Ops Assistant can use them now" in out and "sf.example/authorize" in out


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
    assert _failed({"noInternalIds": True}, "The review is at 2 pm (case_0eef29f68716).") == ["no internal id or name"]
    assert _failed({"noInternalIds": True}, "One item is open (my_human_tasks).") == ["no internal id or name"]
    assert _failed({"noControls": True}, 'Press the card\'s "Open briefing" button.') == ["names no control"]
    twice = _seen("The case is below.", [])
    twice["tools"] = [{"name": "get_case", "input": {"caseId": "c1"}}] * 2
    assert [n for n, ok, _ in chat_script.reply_checks({"noRepeatCalls": True}, twice, {}) if not ok] == [
        "no call sent twice"
    ]
    twice["tools"][1] = {"name": "get_case", "input": {"caseId": "c1"}, "output": {"repeatOf": "x"}}
    assert all(ok for _, ok, _ in chat_script.reply_checks({"noRepeatCalls": True}, twice, {}))
    asked = _seen("Policy says ten days.", ["my_human_tasks", "search_knowledge"])
    failed = [n for n, ok, _ in chat_script.reply_checks({"notTools": ["my_human_tasks"]}, asked, {}) if not ok]
    assert failed == ["does not call my_human_tasks"]
    case = {"output": {"cards": [{"type": "case", "id": "c1"}]}}
    assert _failed({"cardsOnce": True}, "Done.", {"toolCalls": [case, case]}) == ["each card drawn once"]
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


def test_the_log_flow_checks_see_quick_replies_and_a_pending_approval() -> None:
    # An interview reply with no chips, or a save that never waited for its review, passed every other check.
    plain = _seen("Update Education savings, or open a new one?")
    assert [n for n, ok, _ in chat_script.reply_checks({"followUps": True}, plain, {}) if not ok] == [
        "offers quick replies"
    ]
    asked = {"followUps": ["Update Education savings", "Open a new one"]}
    assert all(ok for _, ok, _ in chat_script.reply_checks({"followUps": 2}, plain, asked))
    saved = {"widgets": [{"id": "w1", "state": "approved"}]}
    assert [n for n, ok, _ in chat_script.reply_checks({"approval": True}, plain, saved) if not ok] == [
        "waits on an approval"
    ]
    waiting = {"widgets": [{"id": "w1", "state": "pending"}]}
    assert all(ok for _, ok, _ in chat_script.reply_checks({"approval": True}, plain, waiting))


def test_the_widget_check_names_the_card_kind_the_reply_drew() -> None:
    # A prep answered in prose passed every text check while the brief card never appeared.
    plain = _seen("Grace Okafor is the trustee.")
    drew = {"parts": [{"type": "text"}, {"type": "widget", "kind": "brief"}]}
    assert all(ok for _, ok, _ in chat_script.reply_checks({"widget": "brief"}, plain, drew))
    assert [n for n, ok, _ in chat_script.reply_checks({"widget": ["brief", "form"]}, plain, drew) if not ok] == [
        "draws a form card"
    ]


def test_the_memory_and_card_checks_read_the_stored_reply() -> None:
    # A form drawn on the questions-first log flow, or a standing rule kept only as a suggestion, passed unnoticed.
    plain = _seen("Which stage did you agree?")
    drew = {"parts": [{"type": "widget", "kind": "form"}], "remembered": [{"status": "suggested"}]}
    failed = [
        n
        for n, ok, _ in chat_script.reply_checks({"notWidgets": ["form"], "remembers": "active"}, plain, drew)
        if not ok
    ]
    assert failed == ["draws no form card", "keeps a memory as active"], failed
    kept = {"parts": [], "remembered": [{"status": "active"}]}
    assert all(
        ok for _, ok, _ in chat_script.reply_checks({"notWidgets": ["form"], "remembers": "active"}, plain, kept)
    )


def test_the_plan_check_reads_the_checklist_the_reply_drew() -> None:
    # A multi-step answer with no checklist, or one left open, passed every text check.
    plain = _seen("Two files need you.")
    done = {"parts": [{"id": "wp_plan", "hint": {"title": "Did 3 steps"}, "data": [{"state": "done"}] * 3}]}
    open_ = {"parts": [{"id": "wp_plan", "hint": {"title": "Check"}, "data": [{"state": "done"}, {"state": "failed"}]}]}
    assert all(ok for _, ok, _ in chat_script.reply_checks({"plan": "done"}, plain, done))
    assert not all(ok for _, ok, _ in chat_script.reply_checks({"plan": "done"}, plain, open_))
    assert all(ok for _, ok, _ in chat_script.reply_checks({"plan": "blocked"}, plain, open_))
    assert not all(ok for _, ok, _ in chat_script.reply_checks({"plan": "done"}, plain, {"parts": []}))


def test_the_model_and_offer_checks_read_the_stored_reply() -> None:
    plain = _seen("Overdue reviews go to the risk committee.")
    deeper = {"settings": {"model": "thinking"}, "followUps": []}
    assert all(ok for _, ok, _ in chat_script.reply_checks({"ranOn": "thinking"}, plain, deeper))
    first = {"settings": {"model": "assistant"}, "followUps": ["Think harder"]}
    assert [
        n
        for n, ok, _ in chat_script.reply_checks({"ranOn": "thinking", "offers": "Think harder"}, plain, first)
        if not ok
    ] == ["ran on thinking"]


CONNECTORS = [
    {
        "appId": "plugin:opsai.salesforce",
        "name": "Salesforce",
        "state": "on",
        "on": True,
        "tools": ["salesforce_query"],
    },
    {"appId": "plugin:opsai.github", "name": "GitHub", "state": "on", "on": True, "tools": ["github_list_issues"]},
    {"appId": "plugin:core", "name": "Core banking", "state": "off_for_team", "on": False, "tools": []},
]


def test_chat_with_connector_leaves_every_other_connector_out_and_refuses_one_it_lacks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def answer(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/connectors") and r.method == "GET":
            return _ok({"threadId": "th_1", "connectors": CONNECTORS})
        if r.url.path.endswith("/connectors"):
            off = json.loads(r.content)["off"]
            return _ok({"threadId": "th_1", "connectors": [{**c, "on": c["appId"] not in off} for c in CONNECTORS]})
        return _ok({"id": "th_1"}, 201)

    seen: list[httpx.Request] = []
    _use(monkeypatch, "chat", _client(seen, answer))
    assert main(["chat", "start", "--connector", "github"]) == 0
    put = next(r for r in seen if r.method == "PUT")
    assert put.url.path == "/api/agents/v1/chat/threads/th_1/connectors"
    # Only the apps the chat holds are turned off; an app the team has off grants nothing to leave out.
    assert json.loads(put.content) == {"off": ["plugin:opsai.salesforce"]}
    assert "GitHub on" in capsys.readouterr().out
    # `--connectors` with a comma list is the same choice.
    assert main(["chat", "start", "--connectors", "github,salesforce"]) == 0
    assert json.loads([r for r in seen if r.method == "PUT"][-1].content) == {"off": []}
    capsys.readouterr()
    assert main(["chat", "start", "--connector", "Core banking"]) == 1
    assert "no connector named core banking" in capsys.readouterr().err


def test_connectors_list_is_one_row_per_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        {"name": "GitHub", "state": "connected", "account": "harbor-ops", "accountCount": 2, "canDo": "Reads: issues"}
    ]
    seen: list[httpx.Request] = []
    _use(monkeypatch, "connectors", _client(seen, lambda r: _ok(rows)))
    assert main(["connectors", "list"]) == 0
    assert seen[-1].url.path == "/api/tools/v1/me/connections"
    assert capsys.readouterr().out.strip() == "GitHub  connected  harbor-ops  2  Reads: issues"


def test_the_which_account_card_names_each_account() -> None:
    from ops_ai._chat import connect_card  # noqa: PLC0415

    call = {
        "status": "failed",
        "output": {
            "error": {
                "code": "ACCOUNT_CHOICE_NEEDED",
                "message": "choose",
                "details": {"app": "GitHub", "accounts": [{"account": "harbor-ops"}, {"account": "harbor-sandbox"}]},
            }
        },
    }
    card = connect_card(call)
    assert card is not None and card["reason"] == "account_choice" and len(card["accounts"]) == 2, card


def test_a_script_that_expects_the_off_for_team_card_fails_on_a_connect_card() -> None:
    want = {"card": "app_off"}
    connect = {**_seen("Connect it above."), "cards": [{"connection": "Salesforce", "reason": "not_connected"}]}
    off = {**_seen("Ask an admin above."), "cards": [{"app": "Salesforce", "reason": "app_off"}]}
    assert [n for n, ok, _ in chat_script.reply_checks(want, connect, {}) if not ok] == ["app_off card shown"]
    assert [n for n, ok, _ in chat_script.reply_checks(want, off, {}) if not ok] == []


def test_a_script_whose_person_lacks_two_accounts_skips_without_a_chat(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    rows = [{"appId": "plugin:opsai.github", "name": "GitHub", "accountCount": 1}]
    seen: list[httpx.Request] = []
    _use(monkeypatch, "chat", _client(seen, lambda r: _ok(rows)))
    script = tmp_path / "s.json"
    needs = {"app": "GitHub", "accounts": 2}
    script.write_text(json.dumps({"needs": needs, "turns": [{"say": "Issues?", "expect": {"card": "account_choice"}}]}))
    assert main(["chat", "script", str(script)]) == 0
    assert "SKIP s.json: needs two different GitHub logins" in capsys.readouterr().out
    assert not any(r.url.path.endswith("/chat/threads") for r in seen), "no chat is started"
