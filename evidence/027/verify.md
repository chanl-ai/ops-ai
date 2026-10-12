<!-- codeloop verify: start -->
# Verify c-027

result: pass
sha: 8535924c40dd35b6b24f95a0a57d1552f487c1d1
env: local

| Use case | Accepts | Layers |
|---|---|---|
| us1-edit-call-staged | US1 | cli pass |
| us2-edit-refused | US2 | cli pass |
| us3-response-transform | US3 | cli pass |
| us4-operation-timeout | US4 | cli pass |
| us5-sheet-http-section | US5 | cli pass |
<!-- codeloop verify: end -->

## Live walk

stack: `make up` (shared stack: console :3016 with NEXT_PUBLIC_OPS_TOOLS_API_URL from 339dc72, tools-service :8720 restarted on c-027's code with `make restart SVC=tools` and `SVC=console`). A Playwright browser drove the console; setup used tools-service's API only where the console has no screen.
url: http://localhost:3016/tools/mod_6857637c8ee9

steps:
- Setup through tools-service's API: listed statements.bank.test on the egress allow-list and created a blank HTTP module (mod_6857637c8ee9).
- On the module page, Add operation with `GET https://statements.bank.test/v1/accounts/{accountId}/statements`: the row appeared and the test panel's operation picker showed the new operation (it was empty before ffcf7a9). Screenshot: live-1-first-operation-test-panel.png
- Security approved the first review through the API, because the console has no decide screen yet (c-040): published v0.1.0.
- Opened the operation's sheet: the HTTP call section showed GET and the full URL. Screenshot: live-2-http-section-published.png
- Changed the URL to `https://statements.bank.test/v2/statements/latest`: the sheet warned "accountId is an input of this operation, but the URL, headers and body never use it". Stage change: the page showed 1 unpublished change (major), and the sheet header read "GET /v2/statements/latest · staged; calls run the published call until you publish". Screenshot: live-3-staged-path-edit.png
- Publish version: the dialog asked "Publish a major version?"; after Publish, tools-service reported v1.0.0 with a security review pending and the path /v2/statements/latest. Screenshot: live-4-published-major.png
- No page errors.

network:
- GET http://localhost:8720/v1/tool-modules/mod_6857637c8ee9 200
- POST http://localhost:8720/v1/tool-modules/mod_6857637c8ee9/operations 200
- GET http://localhost:8720/v1/tool-modules/mod_6857637c8ee9 200
- GET http://localhost:8720/v1/tool-modules/mod_6857637c8ee9 200
- PATCH http://localhost:8720/v1/tool-modules/mod_6857637c8ee9/operations/mod_6857637c8ee9_op1 200
- GET http://localhost:8720/v1/tool-modules/mod_6857637c8ee9 200
- POST http://localhost:8720/v1/tool-modules/mod_6857637c8ee9/versions 200
- GET http://localhost:8720/v1/tool-modules/mod_6857637c8ee9 200

external: none: this walk edits and publishes an operation's definition, which never calls the outbound system; real outbound calls are c-038's card (they time out on this stack today), and uc-010 api shows edited calls reaching the https fake bank through the gateway.
