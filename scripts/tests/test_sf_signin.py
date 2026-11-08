"""The Salesforce test sign-in tool, by failure mode: a missing .env key found only after signing in (or by printing
the file), and a JWT bearer assertion Salesforce would refuse for its issuer, subject, audience or lifetime."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SCRIPT = Path(__file__).resolve().parents[1] / "sf_signin.py"
spec = importlib.util.spec_from_file_location("sf_signin", SCRIPT)
assert spec and spec.loader
sf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sf)


def test_env_names_each_missing_key_and_signs_no_one_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER_SECRET=do-not-read\nSF_TEST_USERNAME=qa@bank.example\n")
    monkeypatch.setenv("OPS_ENV_FILE", str(env))
    for k in sf.ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sf, "person", lambda _who: pytest.fail("signed in before the keys were checked"))
    with pytest.raises(SystemExit) as stop:
        asyncio.run(sf.run("env", "priya", "Salesforce"))
    said = capsys.readouterr().err
    assert stop.value.code == 2
    assert "SF_TEST_CLIENT_ID, SF_TEST_JWT_KEY_FILE" in said and "SF_TEST_USERNAME" not in said, said
    assert "do-not-read" not in said and "qa@bank.example" not in said, "no value is printed"


def test_the_assertion_carries_what_salesforce_checks() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    token = sf.jwt_assertion("3MVG.consumer", "qa@bank.example", "https://test.salesforce.com/", pem, now=1_000)
    audience = "https://test.salesforce.com"
    claims = jwt.decode(token, key.public_key(), algorithms=["RS256"], audience=audience, options={"verify_exp": False})
    assert claims == {
        "iss": "3MVG.consumer",
        "sub": "qa@bank.example",
        "aud": "https://test.salesforce.com",
        "exp": 1_180,
    }
