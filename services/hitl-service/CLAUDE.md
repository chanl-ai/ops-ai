# hitl-service: working rules

Status: stub folder.

There is no hitl-service and no code here: the folder holds a `Makefile` (every verb answers "not started", through
`make/service-stub.mk`) and a `README.md`. Reviews, approval-token minting and decisions live in
`services/agents-service` today and move into the planned `ops_hitl` package, which agents-service will host. Do
not add code to this folder; work on Reviews in [agents-service](../agents-service/CLAUDE.md).

Design: [docs/architecture/human-in-the-loop.md](../../docs/architecture/human-in-the-loop.md) and
[docs/architecture/service-map.md](../../docs/architecture/service-map.md).

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [layers and ownership](../../docs/architecture/standards/layers.md) (`LY1` to `LY9`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
