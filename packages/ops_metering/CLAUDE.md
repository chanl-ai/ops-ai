# ops_metering: working rules

Status: current.

Model usage accounting with no I/O: usage rows, price lookup by model alias, cost, totals and budget checks. Callers
own storage and decide what happens at a cap. Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide
rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Public API | `Price`, `PriceTable` (`parse`, `price`, `priced`), `Usage`, `cost`, `Totals`, `total`, `Budget`, `Exhausted`, `exhausted` (all in `src/ops_metering/__init__.py`) |
| Contract | Money is `Decimal` rounded to millionths of the currency unit, so totals summed in any order agree to the cent. An alias with no price costs zero and still meters tokens; `priced` tells the two apart |
| Used by | agents-service (thread budgets), models-service (key ledgers) |
| Tests | None here; covered by `make test PKG=services/agents-service T=tests/api/test_chat_budget.py` and models-service's suite |
| Lint, types | `uv run ruff check packages/ops_metering`, `uv run pyright packages/ops_metering` |

Design: [docs/architecture/decisions/ai-gateway.md](../../docs/architecture/decisions/ai-gateway.md).
