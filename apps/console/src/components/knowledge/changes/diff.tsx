'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export interface DiffPart {
  type: 'same' | 'add' | 'del';
  text: string;
}

/** Above this many LCS cells the diff falls back to showing both versions side by side. */
const MAX_LCS_CELLS = 1_000_000;

/** Longest-common-subsequence diff over tokens. Adapted from the shared component library's revision diff (`diffLines`). */
function diffTokens(a: string[], b: string[]): DiffPart[] | null {
  if (a.length * b.length > MAX_LCS_CELLS) return null;
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffPart[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ type: 'same', text: a[i++] });
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ type: 'del', text: a[i++] });
    else out.push({ type: 'add', text: b[j++] });
  }
  while (i < a.length) out.push({ type: 'del', text: a[i++] });
  while (j < b.length) out.push({ type: 'add', text: b[j++] });
  return out;
}

export const diffLines = (from: string, to: string) => diffTokens(from.split('\n'), to.split('\n'));

type Row = { kind: 'same' | 'add' | 'del'; parts: DiffPart[] };

/**
 * A removed line followed by an added one is treated as an edit, and the words that changed are marked inside
 * it. Passages are short and edits are usually one figure, so a whole-line swap hides what moved.
 */
function toRows(lines: DiffPart[]): Row[] {
  const rows: Row[] = [];
  for (let k = 0; k < lines.length; k++) {
    const l = lines[k];
    const next = lines[k + 1];
    if (l.type === 'del' && next?.type === 'add') {
      const words = diffTokens(l.text.split(/(\s+)/), next.text.split(/(\s+)/));
      if (words) {
        rows.push({ kind: 'del', parts: words.filter((w) => w.type !== 'add') });
        rows.push({ kind: 'add', parts: words.filter((w) => w.type !== 'del') });
        k++;
        continue;
      }
    }
    rows.push({ kind: l.type, parts: [{ type: 'same', text: l.text }] });
  }
  return rows;
}

/** Unified before/after view of one passage. Adapted from the shared component library's `DiffLinesView`. */
export function PassageDiff({ before, after, className }: { before: string; after: string; className?: string }) {
  const lines = React.useMemo(() => diffLines(before, after), [before, after]);
  if (!lines)
    return (
      <div className={cn('grid gap-3 sm:grid-cols-2', className)}>
        {[
          ['Before', before],
          ['After', after],
        ].map(([label, text]) => (
          <div key={label} className="min-w-0">
            <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
            <pre className="max-h-80 overflow-y-auto rounded border bg-background p-2 font-mono text-xs break-words whitespace-pre-wrap">{text}</pre>
          </div>
        ))}
      </div>
    );
  return (
    <pre className={cn('rounded-md border bg-muted/30 p-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap', className)} data-testid="passage-diff">
      {toRows(lines).map((r, i) => (
        <div
          key={i}
          className={cn(
            'px-1',
            r.kind === 'add' && 'bg-green-500/10 text-green-800 dark:text-green-300',
            r.kind === 'del' && 'bg-red-500/10 text-red-800 dark:text-red-300',
          )}
        >
          <span aria-hidden className="select-none">{r.kind === 'add' ? '+ ' : r.kind === 'del' ? '- ' : '  '}</span>
          <span className="sr-only">{r.kind === 'add' ? 'Added: ' : r.kind === 'del' ? 'Removed: ' : ''}</span>
          {r.parts.map((p, k) =>
            p.type === 'same' ? (
              <React.Fragment key={k}>{p.text}</React.Fragment>
            ) : (
              <mark key={k} className={cn('rounded-sm px-0.5 text-inherit', p.type === 'add' ? 'bg-green-500/30' : 'bg-red-500/30 line-through decoration-red-700/50')}>
                {p.text}
              </mark>
            ),
          )}
        </div>
      ))}
    </pre>
  );
}
