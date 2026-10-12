<!-- codeloop verify: start -->
# Verify c-028

result: pass
sha: 6083ba142db7e2b02242e56a4fd3f64e8db8fb84
env: local

| Use case | Accepts | Layers |
|---|---|---|
| us1-rate-limit-refuses | US1 | cli pass |
| us2-amount-limit-refuses | US2 | cli pass |
| us3-one-check-panel-and-gateway | US3 | cli pass |
| us4-console-says-what-holds | US4 | cli pass |
<!-- codeloop verify: end -->

## Live walk

stack: `make up` (shared stack: console :3016, tools-service :8720 restarted on 19e257b with `make restart SVC=tools`, which migrated to tools_0007_rate_windows). A Playwright browser drove the console; the calls went to tools-service's /v1/calls with agents-service's Ed25519 service token, as agents-service sends them, because the console's test panel runs nothing and spends no rate.
url: http://localhost:3016/tools/mod_core_banking

steps:
- Opened Core banking, clicked get_loan_account, and set its rate limit to 1 in the operation sheet; the hint read "Calls a minute for this operation, across every caller." Screenshot: live-1-rate-limit-set.png
- Stage change: tools-service took the patch and the page showed 1 unpublished change. Screenshot: live-2-rate-limit-staged.png
- Called get_loan_account three times through /v1/calls in the same minute: the first ran (200), the second and third were refused 429 RATE_LIMITED with resetAt 2026-10-12T18:21:00+00:00.
- Opened the Activity tab: "Denied · 24h 2, Refused at the gateway", the two refusals. Screenshot: live-3-activity-shows-the-refusal.png
- Discarded the staged change, so get_loan_account is back to its seeded 120 a minute on the shared stack.
- No page errors.

network:
- GET http://localhost:8720/v1/tool-modules/mod_core_banking 200
- PATCH http://localhost:8720/v1/tool-modules/mod_core_banking/operations/mod_core_banking_op1 200
- GET http://localhost:8720/v1/tool-modules/mod_core_banking 200
- POST http://127.0.0.1:8720/v1/calls 200
- POST http://127.0.0.1:8720/v1/calls 429
- POST http://127.0.0.1:8720/v1/calls 429
- GET http://localhost:8720/v1/tool-modules/mod_core_banking/activity 200

external: none: the limits are decided inside the gateway before anything leaves it, and a refused call by design reaches no outside system; uc-011 and tests/test_call_limits.py show on the fake bank's side that a refused call sends nothing, and real outbound calls on this stack are c-038's card.
