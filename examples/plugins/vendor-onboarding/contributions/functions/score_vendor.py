"""score_vendor: how risky a new supplier is, from what it told us, its registry record and a sanctions screen.

This file is the code a plugin developer writes. Everything else in the plugin is YAML that declares and wires.

Where it runs. Ops AI runs this function in its code sandbox (runner-service: Python on WASM, no network, no files,
with time, memory and call limits from the module's YAML). The runner loads this file, calls `main(input)` with the
workflow step's mapped input, and puts one object in scope, `ops`:

    ops.call(tool, args)   calls a tool operation this function is bound to (see `bindings` in
                           contributions/code-modules/vendor-scoring.yaml), as the run's own gateway call, so
                           egress, approvals and mocks apply exactly as they do to a workflow step
    ops.secret(name)       a handle to a team secret, handed to a bound call by name; its value never enters here

Keep to the standard library's built-ins: the sandbox has no packages installed. Return something JSON can encode.

Input (mapped by the workflow step):
    vendor   {legalName, country, registrationNumber, annualSpend}, what the supplier filled in
    company  the registry's record for registrationNumber (lookup_company), or null when it has none
    policy   optional {highRiskCountries, spendReviewAbove}, the team's thresholds, set in the workflow's YAML

Output:
    {score: 0-100, band: low | medium | high | blocked, reasons: [str], screeningHits: int}
"""

DEFAULT_POLICY = {
    # ISO country codes a team screens harder. A team changes them in the workflow step's `policy`, not here.
    "highRiskCountries": ["IR", "KP", "SY"],
    "spendReviewAbove": 250000,
}
SUFFIXES = ("incorporated", "limited", "company", "corp", "inc", "ltd", "llc", "plc", "co")


def main(input):
    """The runner's entry point: screen the vendor through the bound tool, then score it."""
    vendor = input.get("vendor") or {}
    screening = ops.call(  # noqa: F821 - `ops` is put in scope by the runner
        "screen_vendor",
        {"legal_name": vendor.get("legalName") or "", "country": vendor.get("country") or ""},
    )
    return score(vendor, input.get("company"), screening, input.get("policy"))


def score(vendor, company, screening, policy=None):
    """The scoring itself, with no calls, so it is unit-tested without a stack."""
    rules = dict(DEFAULT_POLICY)
    rules.update(policy or {})
    reasons = []
    blocked = False
    points = 100

    hits = list((screening or {}).get("hits") or [])
    if hits:
        blocked = True
        lists = ", ".join(sorted({str(h.get("list") or "a sanctions list") for h in hits}))
        reasons.append(f"Named on {lists}: the sanctions screen must be cleared before onboarding.")

    number = vendor.get("registrationNumber") or "(none given)"
    if not company:
        # Unknown to the registry lands in the high band on its own: nothing else said about the vendor is checked.
        points -= 60
        reasons.append(f"The registry has no company with registration number {number}.")
    else:
        status = str(company.get("status") or "unknown")
        if status != "active":
            blocked = True
            reasons.append(f"The registry lists {number} as {status}, not active.")
        years = company.get("yearsTrading")
        if isinstance(years, int | float) and years < 2:
            points -= 30
            reasons.append(f"Trading for {years} year(s), under 2.")
        elif isinstance(years, int | float) and years < 5:
            points -= 10
            reasons.append(f"Trading for {years} years, under 5.")
        given, listed = _plain_name(vendor.get("legalName")), _plain_name(company.get("legalName"))
        if given != listed:
            points -= 20
            reasons.append(
                f"The name given ({vendor.get('legalName')}) differs from the registry's ({company.get('legalName')})."
            )

    country = str(vendor.get("country") or "").upper()
    if country in [str(c).upper() for c in rules["highRiskCountries"]]:
        points -= 25
        reasons.append(f"Registered in {country}, a country on the team's high-risk list.")

    spend = vendor.get("annualSpend") or 0
    if isinstance(spend, int | float) and spend > rules["spendReviewAbove"]:
        points -= 15
        reasons.append(f"Expected annual spend {spend:,} is over the review line of {rules['spendReviewAbove']:,}.")

    points = max(0, points)
    if blocked:
        band = "blocked"
    elif points >= 80:
        band = "low"
    elif points >= 50:
        band = "medium"
    else:
        band = "high"
    return {"score": points, "band": band, "reasons": reasons, "screeningHits": len(hits)}


def _plain_name(name):
    """A company name compared without case, punctuation or a legal suffix: "Acme Ltd." and "ACME" are one name."""
    words = "".join(ch if ch.isalnum() else " " for ch in str(name or "").lower()).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)
