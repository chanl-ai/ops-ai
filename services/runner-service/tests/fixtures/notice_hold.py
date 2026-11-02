"""settle: one function a test can send on its own.

The runner execs this function's source and puts `ops` and `OpsError` in scope. Nested helpers stay inside the
function so `inspect.getsource(settle)` is the whole tool.
"""

from __future__ import annotations

from typing import Any


def settle(input: dict[str, Any]) -> dict[str, Any]:
    """Post each payment against the account the bank returns. A refused account is reported, not fatal."""

    def money(value: Any) -> float:
        return round(float(value or 0), 2)

    def as_record(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, Any] = {}
        pairs: Any = value.items()  # pyright: ignore[reportUnknownVariableType]
        for key, item in pairs:
            out[str(key)] = item
        return out

    def line_for(row: dict[str, Any], posted: dict[str, Any]) -> dict[str, Any]:
        asked = money(row.get("amount"))
        have = money(posted.get("balance"))
        taken = money(min(asked, have)) if posted.get("status") == "open" else 0.0
        return {"id": row["id"], "taken": taken, "short": money(asked - taken)}

    gateway: Any = globals()["ops"]
    key = gateway.secret("BANK_API_KEY")
    settled: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    payments: Any = input.get("payments") or ()
    for row in payments:
        payment = as_record(row)
        try:
            posted = as_record(gateway.call("get_account", {"accountId": payment["accountId"], "key": key}))
        except Exception as e:
            if type(e).__name__ != "OpsError":
                raise
            refused.append({"id": payment["id"], "code": getattr(e, "code", "")})
            continue
        settled.append(line_for(payment, posted))
    taken = round(sum(float(item["taken"]) for item in settled), 2)
    print("settled", len(settled), "refused", len(refused))
    return {"taken": taken, "lines": settled, "refused": refused}
