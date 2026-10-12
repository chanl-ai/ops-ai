# c-028 independent review

One entry per commit, by a reviewer that did not build it. Each check ran on a clean `git archive` export of the
commit against a private database (`ops_review_c028`); the working tree was never edited. Probes ran as extra tests in
that export only. Zero real model calls.

## 19e257b: rate and amount limits hold on /v1/calls

- Check: tools-service `make verify` on the export: lint and pyright clean, 71 passed. `make usecase-test UC=uc-011
  LAYER=api`: 15 checks.
- Read: the rate counter is one atomic upsert per tenant, operation and minute on the database clock, spent only after
  every other check passes and, for a write, after the claim says it is a first execution; a rate-refused write gives
  its claim back. The amount check runs before the policy and before any request is built, and the test panel uses
  the same `amount_refusal`.
- walk repeated: called get_loan_account through /v1/calls on the shared make up stack until refused -> after 119
  allowed calls (plus one probe call that minute) the next was refused and Activity showed it denied with the reason,
  POST http://127.0.0.1:8720/v1/calls 429 RATE_LIMITED, resetAt 2026-10-12T18:27:00+00:00.
- Verdict: reject.
- Defect (probed): the amount limit compares `amount > amount_max` only, so a negative amount passes any cap. With
  `place_hold` at `amount_max=500` and an approval token, `amount: -5000000` was allowed (200, decision allow) and
  `{"accountId":"CHQ-2219","hours":24,"amount":-5000000}` reached the upstream. A cap on a money-moving operation that a
  sign flip skips is no cap. Fix: refuse a negative amount (or cap its magnitude) in `limits.amount_refusal`, with this
  probe as a test.
- Note: the gateway's own rate refusal and an upstream 429 both use the code `RATE_LIMITED`; they differ by decision
  (deny against allow) and, after c-038 (d652d06), by the upstream's `side`. Worth a distinct code if callers read it.

## 1e513d0: the mock's test panel refuses amounts the way the gateway does

- Check: the rule in `mock/tool-modules/amount.ts` mirrors `limits.amount_refusal` line for line; console verify ran in
  the c-027 review export at HEAD then.
- Verdict: reject, with 19e257b: it copies the same `amount > amountMax` comparison, so the mock allows a negative
  amount too. Change both rules together so the panel and the gateway keep agreeing.

## fef28ac: a negative amount is refused, not waved past the cap

- Check: on a clean export, `limits.amount_refusal` with `amount_max=500`: -5000000, -1e-9 and "-1" are 422
  `invalid_input`; -0.0, "-0" and 0 pass as zero; 500 passes; 500.01 is 403 `amount_over_limit`. The mock's `amount.ts`
  adds the same `amount < 0` refusal. `make usecase-test UC=uc-011 LAYER=api`: 15 checks, including the -5,000,000
  parity case on both sides; tools-service verify green on the export (85 passed with c-038's 8bd4a29 beside it).
- Verdict: accept. Closes the 19e257b and 1e513d0 rejects.
- Note: keeping `RATE_LIMITED` for the gateway's own refusal is fine as the card's US1 names it; the two cases differ
  by decision and by `side`.

## Card verdict

19e257b and 1e513d0 were rejected for a negative amount passing the cap; fef28ac refuses it in the gateway and the
mock and is accepted, so every c-028 commit now stands accepted.

walk repeated: the builder's step of calling get_loan_account past its rate limit -> the 121st call that minute was
refused and Activity showed it denied with the reason, POST http://127.0.0.1:8720/v1/calls 429 RATE_LIMITED

verdict: approve
