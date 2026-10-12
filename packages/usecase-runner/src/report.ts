// The contract between a use case script and the runner. A script prints one line per check, `PASS <name>` or
// `FAIL <name>: <detail>`, and exits 0 only when every check passed. The runner trusts neither half alone: a zero exit
// with a FAIL line fails, and so does a script that printed no check at all, because a script whose assertions never
// ran would otherwise pass.

export const EXIT = { ok: 0, failed: 1, usage: 2, unavailable: 3 } as const;

export interface Checks {
  passed: string[];
  failed: string[];
}

export function parseChecks(output: string): Checks {
  const passed: string[] = [];
  const failed: string[] = [];
  for (const raw of output.split('\n')) {
    const line = raw.trimEnd();
    if (line.startsWith('PASS ')) passed.push(line.slice(5));
    else if (line.startsWith('FAIL ')) failed.push(line.slice(5));
  }
  return { passed, failed };
}

export type Verdict = { pass: true } | { pass: false; reason: string };

export function verdict(exitCode: number | null, checks: Checks): Verdict {
  if (checks.failed.length) return { pass: false, reason: `${checks.failed.length} check(s) failed` };
  if (exitCode !== 0) return { pass: false, reason: `script exited ${exitCode ?? 'by signal'}` };
  if (!checks.passed.length) return { pass: false, reason: 'script printed no PASS line, so nothing was checked' };
  return { pass: true };
}

export interface Outcome {
  id: string;
  layer: string;
  status: 'PASS' | 'FAIL' | 'UNAVAILABLE';
  detail: string;
}

/** Exit code for a whole invocation: any failure wins; all-unavailable means nothing ran. */
export function exitFor(outcomes: Outcome[]): number {
  if (outcomes.some((o) => o.status === 'FAIL')) return EXIT.failed;
  if (!outcomes.length || outcomes.every((o) => o.status === 'UNAVAILABLE')) return EXIT.unavailable;
  return EXIT.ok;
}

export function summary(outcomes: Outcome[]): string {
  const w = Math.max(6, ...outcomes.map((o) => o.id.length));
  return outcomes.map((o) => `${o.status.padEnd(11)} ${o.id.padEnd(w)} ${o.layer.padEnd(4)} ${o.detail}`).join('\n');
}
