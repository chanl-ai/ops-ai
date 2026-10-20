// The gateway's amount rule (tools-service ops_tools/limits.py), for the mock's test panel: the limit reads the
// operation's `amount` input, and when the operation declares one a missing, non-numeric or negative amount is refused too, so
// the console never shows a limit the gateway does not hold. No imports, so uc-011 can run it beside the Python rule.
export function amountRefused(o: { amountMax?: number | null; input: { name: string }[] }, args: Record<string, unknown>): boolean {
  if (o.amountMax == null || !o.input.some((f) => f.name === 'amount')) return false;
  const raw = args.amount;
  const amount = typeof raw === 'number' ? raw : typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : NaN;
  return !Number.isFinite(amount) || amount < 0 || amount > o.amountMax;
}
