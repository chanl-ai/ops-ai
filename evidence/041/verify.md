<!-- codeloop verify: start -->
# Verify c-041

result: pass
sha: a12946d15b629506104de09da5e3772796cd6aa4
env: local
workspace: export of a12946d

| Use case | Accepts | Layers |
|---|---|---|
| us1-traffic-from-the-call-log | US1 | cli pass |
| us2-activity-from-the-call-log | US2 | cli pass |
| us3-new-module-zero-and-expiring | US3 | cli pass |
<!-- codeloop verify: end -->

## Live walk

stack: make up ISOLATED=1 AUTH=platform (console :4016 signing in through platform-service :9710; tools :9720 verifying platform tokens)
url: http://localhost:4016/tools/mod_aef7b3232e4e?tab=activity

steps:
- Setup through tools-service's API: Priya Shah (admin) listed postman-echo.com (201); James Richardson created module mod_aef7b3232e4e with echo_get_tpj6 (GET https://postman-echo.com/get) and echo_unavailable_tpj6 (GET https://postman-echo.com/status/503); Nadia Petrov approved its review, published at v0.1.0.
- Before any call, James's module page and the API read 0 calls, 0 error rate, 0 ms p95, and today's activity 0. Screenshot: live-1-before-calls.png
- Four real calls through /v1/calls with the agents service token: echo_get_tpj6 three times, each 200 ok from postman-echo.com; echo_unavailable_tpj6 once, ok=false UPSTREAM_ERROR "postman-echo.com answered 503." side upstream.
- After: the module reads 4 calls, error rate 0.25, p95 176 ms; echo_get_tpj6 3 calls 0% p95 170 ms, echo_unavailable_tpj6 1 call 100% p95 153 ms; today's activity 4 calls, 1 error. Operations tab: live-2-operations-after-calls.png
- Activity tab: Calls · 24h 4, Error rate 25.0%, p95 176 ms, Denied 0, the chart's today at 4 with one failed, the executions listing both operations. Screenshot: live-3-activity-after-calls.png
- Defect found on the walk and fixed in b5a0c3e: the "natural" curve drew the call count below zero between an empty day and today, and the p95 line plotted 0 ms for empty days. The screenshot above is after the fix.
- Replay re-walk after proto-worker-2's change request (c2c935b, 5332623): James published "Echo write walk jbir" (mod_2f6c30be1487) with one write, echo_post_jbir (POST https://postman-echo.com/post). The same approved write sent twice through /v1/calls: the first ran (200, gwc_43be87a3b25b); the second answered with replayOf gwc_43be87a3b25b. /v1/executions lists one ok row and one "replayed" row naming gwc_43be87a3b25b; Calls · 24h is 1. The Activity table reads "Replay of gwc_43be87a3b25b". Screenshot: live-4-replay-in-activity.png

network:
- POST http://127.0.0.1:9720/v1/egress/hosts 201
- POST http://127.0.0.1:9720/v1/tool-modules/blank 201
- POST http://127.0.0.1:9720/v1/tool-modules/mod_aef7b3232e4e/reviews/{id}/decide 200
- POST http://127.0.0.1:9720/v1/calls 200 (x4: three ok, one UPSTREAM_ERROR 503)
- GET https://postman-echo.com/get 200 (x3, sent by tools-service's egress)
- GET https://postman-echo.com/status/503 503 (sent by tools-service's egress, by design)
- POST https://postman-echo.com/post 200 (once: the replay sent nothing)
- GET http://localhost:9720/v1/tool-modules/mod_aef7b3232e4e 200
- GET http://localhost:9720/v1/tool-modules/mod_aef7b3232e4e/activity 200

external: https://postman-echo.com/get

The four calls went through tools-service's egress to postman-echo.com: three to /get (200) and one to /status/503 (503 by design). The numbers on the page are those calls.
