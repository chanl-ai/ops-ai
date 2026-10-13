<!-- codeloop verify: start -->
# Verify c-045

result: pass
sha: 397db7b5cc6cb6c12689b7ffbd9b6cd137bebd4e
env: local
workspace: export of 397db7b

| Use case | Accepts | Layers |
|---|---|---|
| us1-settings-without-shared-token | US1 | cli pass |
| us2-docs-name-the-service-keys | US2 | cli pass |
| us3-calls-run-without-it | US3 | cli pass |
<!-- codeloop verify: end -->

## Live walk

stack: `make up` in the ops-ai-wt-api worktree (its own stack: console :6016, platform :11710, agents-service :11700, tools-service :11720 on database ops_wt_api, built from branch feat/kit-drop-shared-service-token at ec26f09 on main abbb691; the branch since rebased onto main 236dd0c, whose five new commits touch only the console sidebar), with no OPS_SERVICE_TOKEN in the worktree's .env or the environment. A Playwright browser drove the console; the second person's decision and the workflow's call went through the APIs, as in c-039's walk.
url: http://localhost:6016/tools/mod_core_banking

steps:
- Opened Core banking, Access, Request approval: chose agents-service's Dispute email, get_customer_profile and a justification. tools-service read the workflow from agents-service over its Ed25519 service token and created the request (201). Screenshot: live-1-approval-requested-over-a-service-token.png
- Maya Okafor (X-Dev-User) approved it: 200.
- Ran get_customer_profile through /v1/calls as workflow:dispute_email with agents-service's Ed25519 token for tools-service: 200; Activity shows the call. Screenshot: live-2-call-ran-over-a-service-token.png
- No page errors.

network:
- GET http://localhost:11720/v1/tool-modules/mod_core_banking 200
- GET http://localhost:11700/v1/workflows 200
- POST http://localhost:11720/v1/tool-modules/mod_core_banking/approvals 201
- GET http://localhost:11720/v1/tool-modules/mod_core_banking 200
- POST http://127.0.0.1:11720/v1/tool-modules/mod_core_banking/approvals/apr_ba125b2ec454/decide 200
- POST http://127.0.0.1:11720/v1/calls 200
- GET http://localhost:11720/v1/tool-modules/mod_core_banking/activity 200

external: none: this card removes a setting; the walk exercises the internal service-to-service calls that replaced it, and get_customer_profile runs on Core banking's stub on this stack.
