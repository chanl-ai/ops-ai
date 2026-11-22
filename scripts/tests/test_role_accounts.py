"""Role accounts on a deployed install (deploy/fly/role_accounts.py, scripts/api_as.py), by failure mode: an account
that cannot sign in passes the deploy; a role with no account is skipped quietly; an account holding another role
counts as that role; `make api ENV=staging AS=<role>` has no account to use or refuses without naming the fix; the
seed invites a person who is already a member, skips one who is not, invents an account on a runner, or prints an
address into a public deploy log.
The install is a stub at the HTTP edge; the real one is checked by `make roles-check ENV=staging`."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEAM = "team_demo"


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


role_accounts = load("role_accounts", ROOT / "deploy" / "fly" / "role_accounts.py")


class Install:
    """A platform-service that knows `people` (email -> password, role held in TEAM) and records each sign-in."""

    def __init__(self, people: dict[str, tuple[str, str]]) -> None:
        self.people = people
        self.sign_ins: list[str] = []
        self.members: list[dict[str, str]] = []
        self.invited: list[tuple[str, str]] = []
        self.accepted: list[tuple[str, str]] = []
        install = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, status: int, data: Any) -> None:
                body = json.dumps({"data": data}).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/v1/settings/members/invite":
                    install.invited.append((sent["emails"][0], sent["role"]))
                    return self.reply(200, {"invites": [{"token": sent["emails"][0]}]})
                if self.path.startswith("/v1/invites/"):
                    install.accepted.append((self.path.split("/")[3], sent["password"]))
                    return self.reply(200, {})
                install.sign_ins.append(sent["email"])
                known = install.people.get(sent["email"])
                if known and known[0] == sent["password"]:
                    self.reply(200, {"token": sent["email"]})
                else:
                    self.reply(401, None)

            def do_GET(self) -> None:
                if self.path.startswith("/v1/settings/members"):
                    # Two rows a page, so a member on a later page is found only by a caller that reads every page.
                    page = int(self.path.split("page=")[1].split("&")[0])
                    rows = install.members[(page - 1) * 2 : page * 2]
                    return self.reply(200, {"data": rows, "pagination": {"hasNext": page * 2 < len(install.members)}})
                email = self.headers["Authorization"].removeprefix("Bearer ")
                self.reply(200, {"teams": [{"id": TEAM, "role": install.people[email][1]}]})

            def log_message(self, *_: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"


def roles_file(tmp: Path, monkeypatch: pytest.MonkeyPatch, roles: dict[str, str]) -> None:
    """staging-roles.env with `<role>@x` / the given password for each role."""
    lines = [f"STG_ROLES_TEAM={TEAM}"]
    for role, password in roles.items():
        lines += [f"STG_ROLE_{role.upper()}_EMAIL={role}@x", f"STG_ROLE_{role.upper()}_PASSWORD={password}"]
    (tmp / "staging-roles.env").write_text("\n".join(lines) + "\n")
    monkeypatch.setenv("OPS_STAGING_CONFIG", str(tmp))


def test_refused_missing_and_wrong_role_accounts_each_fail_with_their_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # admin is fine; builder's password differs on the install; approver holds viewer; chat_user has no entry.
    install = Install(
        {
            "admin@x": ("pw", "admin"),
            "builder@x": ("other", "builder"),
            "approver@x": ("pw", "viewer"),
            "viewer@x": ("pw", "viewer"),
        }
    )
    roles_file(tmp_path, monkeypatch, dict.fromkeys(("admin", "builder", "approver", "viewer"), "pw"))

    failed = role_accounts.check(install.origin, dev=False)

    out = capsys.readouterr().out.splitlines()
    assert failed == 3
    assert out[0].startswith("ok role admin") and out[3].startswith("ok role viewer")
    assert out[1].startswith("FAIL role builder: sign-in answered 401") and "reset it in the console" in out[1]
    assert out[2].startswith("FAIL role approver: signed in, but holds viewer")
    assert out[4].startswith("FAIL role chat_user: no account") and "make seed-roles ENV=staging" in out[4]
    # One sign-in per account that has an entry and none for the role without one: wrong passwords lock an address.
    assert install.sign_ins == ["admin@x", "builder@x", "approver@x", "viewer@x"]


def test_api_as_on_staging_uses_the_role_account_and_names_the_fix_for_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import api_as  # noqa: PLC0415

    roles_file(tmp_path, monkeypatch, {"builder": "pw", "admin": "pw2"})

    assert api_as.credentials("staging", "builder") == ("builder@x", "pw")
    assert api_as.credentials("staging", "team-admin") == ("admin@x", "pw2")
    with pytest.raises(api_as.Refused) as refused:
        api_as.credentials("staging", "chat_user")
    assert "make seed-roles ENV=staging" in refused.value.message


def test_seed_invites_only_the_missing_account_and_never_invents_or_prints_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install = Install({"first@x": ("admin-pw", "admin")})
    # admin, builder and approver are active members, approver on the second page; viewer is not a member; chat_user
    # has no lines in the file.
    install.members = [
        {"id": f"m{n}", "email": f"{role}@x", "role": role, "status": "active"}
        for n, role in enumerate(("admin", "builder", "approver"))
    ]
    roles_file(tmp_path, monkeypatch, dict.fromkeys(("admin", "builder", "approver", "viewer"), "file-pw"))
    admin_env = tmp_path / "admin.env"
    admin_env.write_text("OPS_BOOTSTRAP_ADMIN_EMAIL=first@x\nOPS_BOOTSTRAP_ADMIN_PASSWORD=admin-pw\n")

    failed = role_accounts.seed(install.origin, admin_env, generate=False)

    out = capsys.readouterr().out
    assert install.invited == [("viewer@x", "viewer")]
    assert install.accepted == [("viewer@x", "file-pw")]
    assert failed == 1 and "FAIL role chat_user: no account" in out
    assert "FOUND role approver" in out and "MADE role viewer" in out
    assert "@x" not in out
