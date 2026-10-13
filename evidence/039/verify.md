<!-- codeloop verify: start -->
# Verify c-039

result: pass
sha: 0cc641824b64a6b6206ff62392c87e7b118a9409
env: local
workspace: export of 0cc6418

| Use case | Accepts | Layers |
|---|---|---|
| us1-workflows-from-agents | US1 | cli pass |
| us2-approval-for-a-real-workflow | US2 | cli pass |
| us3-no-tests-at-runtime | US3 | cli pass |
<!-- codeloop verify: end -->

## Live walk

stack: `make up` (shared stack on the main tree: console :3016, agents-service :8700 and tools-service :8720 restarted on 32783c1 with `make restart SVC=agents` and `SVC=tools`, which now migrate first; tools at tools_0008_approval_team). A Playwright browser drove the console; the second person's decision and the workflow's call went through the APIs, because the dev console signs in one person and calls come from agents-service.
url: http://localhost:3016/tools/mod_core_banking

steps:
- Opened Core banking, Access, Request approval: the Workflow picker listed agents-service's workflows ("Dispute email", "Wire hold review"), not the mock's. Chose Dispute email, the get_customer_profile operation and a justification. Screenshot: live-1-request-for-a-real-workflow.png
- Request approval: tools-service answered 201 for dispute_email, named "Dispute email" as agents-service names it. Screenshot: live-2-requested.png
- Maya Okafor (X-Dev-User), not the requester, approved it: 200. The Access tab shows it approved. Screenshot: live-3-approved-by-the-owner-team.png
- Ran get_customer_profile through /v1/calls as workflow:dispute_email with agents-service's service token: 200, and the call log names dispute_email. The test panel's Run as offers "Dispute email · sample values" instead of fixture cases. Screenshot: live-4-call-as-the-workflow.png
- No page errors.

network:
- GET http://localhost:8720/v1/tool-modules/mod_core_banking 200
- GET http://localhost:8700/v1/workflows 200
- POST http://localhost:8720/v1/tool-modules/mod_core_banking/approvals 201
- GET http://localhost:8720/v1/tool-modules/mod_core_banking 200
- POST http://127.0.0.1:8720/v1/tool-modules/mod_core_banking/approvals/apr_dc3225f6066d/decide 200
- POST http://127.0.0.1:8720/v1/calls 200
- GET http://localhost:8720/v1/tool-modules/mod_core_banking/activity 200

external: none: approvals and the workflow list are internal to tools-service and agents-service, and get_customer_profile runs on Core banking's stub on this stack; real outbound calls are c-038's card.
