"""compute_levy_hold, the levy demo's code tool (c-531, c-532): how much of a levy notice the bank holds, and on which
account. It runs on runner-service, so it reaches nothing but `get_levy_rules`, the bank's exempt-funds rules, and
hands that read the bank key by name; the key's value never reaches this function.

Input: `document`, the notice record ({name, amount, case_no, ...}), and `accounts`, the bank's list_accounts answer
([{id, customerId, type, currency, balance, status}]). Output: {holdAmount, accountId, reason}; a holdAmount of 0 means
every account's funds are exempt."""


def main(input):
    rules = ops.call("get_levy_rules", {"rulesKey": ops.secret("BANK_API_KEY")})  # noqa: F821 - given by the runner
    protected = float(rules.get("protectedBalance") or 0)
    currency = rules.get("currency") or "CAD"
    exempt = set(rules.get("exemptAccountTypes") or [])
    amount = float((input.get("document") or {}).get("amount") or 0)

    best = None
    for account in input.get("accounts") or []:
        if account.get("status", "open") != "open":
            continue
        kept = protected if account.get("type") in exempt else 0.0
        available = float(account.get("balance") or 0) - kept
        if best is None or available > best[1]:
            best = (account, available)
    if best is None:
        return {"holdAmount": 0, "accountId": None, "reason": "The customer has no open account to hold funds in."}

    account, available = best
    hold = round(max(0.0, min(amount, available)), 2)
    name = f"{str(account.get('type') or 'account').capitalize()} account {account['id']}"
    if hold == 0:
        reason = f"{name} holds no more than the exempt {protected:,.2f} {currency}, so nothing is held."
    elif account.get("type") in exempt:
        reason = f"{name} keeps its first {protected:,.2f} {currency} exempt; holds {hold:,.2f}."
    elif hold == amount:
        reason = f"{name} is not exempt; holds the notice's {hold:,.2f}."
    else:
        reason = f"{name} is not exempt; holds all {hold:,.2f} available."
    return {"holdAmount": hold, "accountId": account["id"], "reason": reason}
