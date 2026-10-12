<!-- codeloop verify: start -->
# Verify c-038

result: pass
sha: bfdff3adcc186c29289374ffb47d31c906b34bce
env: local
workspace: export of bfdff3a

| Use case | Accepts | Layers |
|---|---|---|
| us1-failure-names-its-side | US1 | cli pass |
| us2-test-environment-reads-the-system | US2 | cli pass |
| us3-live-call-reaches-a-public-host | US3 | cli pass |
<!-- codeloop verify: end -->

codeloop ran the use cases on an export of bfdff3a. uc-038 now starts agents-service beside tools-service and asks
approval for agents-service's dispute_email workflow, since c5ed407 reads approvals' workflows from there. Each use case
is uc-038 with `OPS_LIVE_EGRESS=1`: seven checks, three real https calls to postman-echo.com and one DNS lookup of a
`.invalid` name each run. Zero real model calls.

## Live walk

stack: `make up` (shared stack: console :3016, tools-service :8720 restarted by `make up` on 02e9442 as older than its code; schema in sync, nothing rebuilt). A Playwright browser drove the console; module setup, approvals and the one failing call used tools-service's API, as agents-service would, since the console has no screen for them.
url: http://localhost:3016/tools/mod_49281835202f and http://localhost:3016/tools/mod_d43212ee9ab7

steps:
- Setup through tools-service's API: listed postman-echo.com and nowhere-145215.invalid on the egress allow-list, published "Echo walk" (echo_get_145215 GET /get, echo_post_145215 POST /post) and "Nowhere walk" (lost_145215 GET /get), approved wf_dispute for the echo operations (requested by the builder, decided by a second person).
- Called lost_145215 through /v1/calls as agents-service: answered CONNECT_FAILED, side ours, "nowhere-145215.invalid could not be reached; no connection was made." (no address).
- On Echo walk's test panel, chose echo_get_145215, Run as the dispute case, target Test environment, Run: Allowed, HTTP 200, 162 ms, "from postman-echo.com", with postman-echo's real echo below. Screenshot: live-1-test-environment-read.png
- Chose echo_post_145215, Test environment, Run, then Simulate the approval: "Writes answer from the stub. The test console never writes to the system." Screenshot: live-2-test-environment-write-stub.png
- Opened Nowhere walk's Activity tab: the executions row for lost_145215 reads "Failed" with "Our side · CONNECT_FAILED". Screenshot: live-3-activity-failure-side.png
- No page errors.
- Cookie leak, found on the orchestrator's walk and fixed in 847f317: postman-echo echoed back `sails.sid` and
  `__cf_bm` cookies that the gateway's shared client had stored from an earlier answer, on a call that configured none.
  After `make up` restarted tools-service on 847f317, two /v1/calls to echo_get_145215 echoed no cookie, and the
  orchestrator's re-walk made two Test environment reads in a row (HTTP 200 from postman-echo.com, 143 ms and 57 ms),
  neither echoing a cookie. uc-038 now checks this on every live run (7 checks).
- Seen in passing, not this card: Nowhere walk's Activity summary cards read 0 calls and 0.0% errors while the executions table lists the failed call.

network:
- POST http://127.0.0.1:8720/v1/egress/hosts 201
- POST http://127.0.0.1:8720/v1/tool-modules/blank 201
- POST http://127.0.0.1:8720/v1/tool-modules/mod_49281835202f/operations 200
- POST http://127.0.0.1:8720/v1/tool-modules/mod_49281835202f/operations 200
- POST http://127.0.0.1:8720/v1/tool-modules/mod_49281835202f/reviews 200
- POST http://127.0.0.1:8720/v1/tool-modules/mod_49281835202f/reviews/rev_20548bc29ddd/decide 200
- POST http://127.0.0.1:8720/v1/tool-modules/mod_49281835202f/approvals 201
- POST http://127.0.0.1:8720/v1/tool-modules/mod_49281835202f/approvals/apr_971b053d3c22/decide 200
- POST http://127.0.0.1:8720/v1/egress/hosts 201
- POST http://127.0.0.1:8720/v1/tool-modules/blank 201
- POST http://127.0.0.1:8720/v1/tool-modules/mod_d43212ee9ab7/operations 200
- POST http://127.0.0.1:8720/v1/tool-modules/mod_d43212ee9ab7/reviews 200
- POST http://127.0.0.1:8720/v1/tool-modules/mod_d43212ee9ab7/reviews/rev_2e2caaea55cb/decide 200
- POST http://127.0.0.1:8720/v1/calls 200
- GET http://localhost:8720/v1/tool-modules/mod_49281835202f 200
- POST http://localhost:8720/v1/tool-modules/mod_49281835202f/test 200
- POST http://localhost:8720/v1/tool-modules/mod_49281835202f/test 200
- POST http://localhost:8720/v1/tool-modules/mod_49281835202f/test 200
- GET http://localhost:8720/v1/tool-modules/mod_d43212ee9ab7 200
- GET http://localhost:8720/v1/tool-modules/mod_d43212ee9ab7/activity 200
- GET https://postman-echo.com/get 200 (tools-service's outbound call for the test panel's read, the status and body shown in the panel)

external: https://postman-echo.com/get

The test panel's read reached postman-echo.com (HTTP 200 in 162 ms, its echo shown), and uc-038 reached it through /v1/calls on every run; an unresolvable allowed host failed on our side as CONNECT_FAILED.
