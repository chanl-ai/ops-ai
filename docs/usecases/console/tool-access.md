# Access › Tool access

Status: current. Id: `uc-143`. Service: `console` on tools-service `GET /v1/tool-modules/grants`. Layers: ui.

Access lost its tool access tab when tools-service could list one module's grants only, so nobody could see in one
place which workflows may call which modules. Access › Tool access lists every workflow's access across the modules
the team sees, one view at a time, each view counted on the server.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James asks for a workflow's access to his published module, then opens Access › Tool access | Each view's count (Requested, All and the rest) equals the server's |
| 2 | He opens the Requested view | The console asks for `view=requested`, and his request is listed with its workflow and module |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-143-ui.mjs` | passing |
