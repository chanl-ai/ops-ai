# ops_pii: working rules

Status: current.

Masks personal data in what people see: SSNs and their last four, card and account numbers, emails and phone numbers,
in whole text (`mask`), in a JSON value (`masked`) or streamed (`StreamMasker`, `HOLD`), and any value under a field
named as an SSN, account, card or tax id (`field_kind`: `ssnLast4`, `accountIds`, `taxId`), a number included. Names are not masked: no pattern finds them without a
model call. The caller decides what is shown; the real value stays wherever it is kept. Package rules and test
commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Contract | A pattern is masked whole: streamed text is held back by `HOLD` (32) characters and cut only at whitespace, so a number split across two chunks is masked once, and a field name is released with its value. Ids glued to letters (`fil_13cf…`) are never masked. A name that only mentions an account or card (`accountName`, `cards`) is not a personal data field. The rule: [roles and permissions E34](../../docs/architecture/roles-and-permissions.md) |
| Used by | `ops_agent_kernel.pii` (re-exports `mask`, `masked`, `StreamMasker`, `HOLD`), `ops_service_kit.logging`, documents-service, and agents-service's run reads, batches and Human Tasks |
| Tests | None here; covered by `make test PKG=services/agents-service T=tests/unit/test_pii_masking.py` |
| Lint, types | `uv run ruff check packages/ops_pii`, `uv run pyright packages/ops_pii` |
| Gap | Not listed in `.importlinter`, so its import contracts are unchecked |

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [layers and ownership](../../docs/architecture/standards/layers.md) (`LY1` to `LY9`), [configuration](../../docs/architecture/standards/configuration.md) (`CF1` to `CF6`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
