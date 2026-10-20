'use client';

import { cn } from '@/lib/utils';

type Line = { kind: 'same' | 'add' | 'del'; text: string };

/** Line diff by longest common subsequence; instructions are short enough that O(n·m) is fine. */
function diffLines(before: string, after: string): Line[] {
  const a = before.split('\n');
  const b = after.split('\n');
  const dp = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: Line[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) (out.push({ kind: 'same', text: a[i] }), i++, j++);
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ kind: 'del', text: a[i++] });
    else out.push({ kind: 'add', text: b[j++] });
  }
  while (i < a.length) out.push({ kind: 'del', text: a[i++] });
  while (j < b.length) out.push({ kind: 'add', text: b[j++] });
  return out;
}

/** Current instructions against the generated ones, removed lines red and added lines green. */
export function PromptDiff({ before, after }: { before: string; after: string }) {
  const lines = diffLines(before, after);
  const added = lines.filter((l) => l.kind === 'add').length;
  const removed = lines.filter((l) => l.kind === 'del').length;
  return (
    <div className="flex flex-col gap-2" data-testid="prompt-diff">
      <p className="text-xs text-muted-foreground tabular-nums">
        <span className="text-success-text">+{added}</span> <span className="text-destructive">−{removed}</span> lines against the current instructions
        {!before.trim() && ' (currently empty)'}
      </p>
      <pre className="overflow-x-auto rounded-md border bg-muted/30 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {lines.map((l, i) => (
          <div key={i} className={cn('px-3', l.kind === 'add' && 'bg-success/10 text-success-text', l.kind === 'del' && 'bg-destructive/10 text-destructive line-through decoration-destructive/60')}>
            <span className="mr-2 inline-block w-3 select-none text-muted-foreground">{l.kind === 'add' ? '+' : l.kind === 'del' ? '−' : ' '}</span>
            {l.text || ' '}
          </div>
        ))}
      </pre>
    </div>
  );
}
