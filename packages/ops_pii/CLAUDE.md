# ops_pii: working rules

Status: current.

Masks personal data in what people see: SSNs and their last four, card and account numbers, emails and phone numbers,
in whole text (`mask`) or streamed (`StreamMasker`, `HOLD`). Names are not masked: no pattern finds them without a
model call. The caller decides what is shown; the real value stays wherever it is kept. Package rules and test
commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Contract | A pattern is masked whole: streamed text is held back by `HOLD` (32) characters and cut only at whitespace, so a number split across two chunks is masked once. Ids glued to letters (`fil_13cf…`) are never masked |
| Used by | `ops_agent_kernel.pii` (re-exports `mask`, `StreamMasker`, `HOLD`) and documents-service |
| Tests | None here; covered by `make test PKG=services/agents-service T=tests/unit/test_pii_masking.py` |
| Lint, types | `uv run ruff check packages/ops_pii`, `uv run pyright packages/ops_pii` |
| Gap | Not listed in `.importlinter`, so its import contracts are unchecked |
