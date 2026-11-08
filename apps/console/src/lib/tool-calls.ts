/** A call the reply's own limits stopped before it ran (the kernel words these "Not run: …"): it did nothing to show. */
export function wasNotRun(call: { status?: string; output?: unknown }): boolean {
  if (call.status !== 'failed' || typeof call.output !== 'object' || call.output === null) return false;
  const error = (call.output as { error?: unknown }).error;
  return typeof error === 'string' && error.startsWith('Not run:');
}
