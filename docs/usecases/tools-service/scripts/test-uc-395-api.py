"""uc-395 a tool presents a client certificate from its connection to a system that refuses a handshake without one,
api layer: docs/usecases/tools-service/connections-certificate.md. The bank stand-in serves mtls.bank.test on a
listener that requires a certificate its own CA signed; the connection also names that CA as the system's. No model
call."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

from connection_calls import allow_bank, call, clean, connection, module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, core_bank, data, finish, tools

with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    clean(gw, "uc395")
    allow_bank(gw, bank, bank["mtlsHost"])
    pem = {k: Path(v).read_text() for k, v in bank["mtls"].items()}
    url = f"https://{bank['mtlsHost']}/auth/mtls"

    # 1. The system's CA trusted, no client certificate: the handshake is refused.
    trusted_only = connection(
        gw,
        "uc395 no certificate",
        "none",
        {"test": {"settings": {"trustedCa": pem["ca"]}}},
        base_url=f"https://{bank['mtlsHost']}",
    )
    module(gw, "uc395-without", url, trusted_only["id"])
    without = call(gw, "uc395_without", environment="test")
    check(
        "1 without a client certificate the call fails TLS_FAILED on our side",
        without.get("ok") is False
        and without["output"]["error"]["code"] == "TLS_FAILED"
        and without["output"]["error"]["side"] == "ours",
        without,
    )

    # 2. The certificate and its key set on the connection: the handshake takes it and the call succeeds.
    with_cert = connection(
        gw,
        "uc395 certificate",
        "none",
        {
            "test": {
                "settings": {"clientCertificate": pem["client_cert"], "trustedCa": pem["ca"]},
                "secretValues": {"clientKey": pem["client_key"]},
            }
        },
        base_url=f"https://{bank['mtlsHost']}",
    )
    shown = data(gw.get(f"/v1/connections/{with_cert['id']}"))
    check(
        "2 the private key is set and never shown",
        shown["environments"]["test"]["secrets"]["clientKey"]["set"] and "PRIVATE KEY" not in str(shown),
        shown["environments"]["test"]["secrets"],
    )
    module(gw, "uc395-with", url, with_cert["id"])
    ok = call(gw, "uc395_with", environment="test")
    check("2 with the certificate the system answers", ok.get("ok") is True and ok["output"] == {"mtls": True}, ok)

    # 3. A connection's certificate is presented only on its own calls: the first module still fails.
    again = call(gw, "uc395_without", environment="test", key="again")
    check("3 the module without a certificate still fails after one was presented", again.get("ok") is False, again)
    rows = data(gw.get("/v1/executions", params={"pageSize": 50}))
    check("4 no private key appears in the call log", "PRIVATE KEY" not in str(rows), "key in the log")
finish()
