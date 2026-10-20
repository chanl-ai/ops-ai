'use client';

import { useMemo } from 'react';

import { CopyButton } from '@/components/shared/copy-button';
import { cn } from '@/lib/utils';

/** Value the gateway stores in place of a masked field. */
export const REDACTED = '[redacted]';

type Token = { text: string; cls: string };

// Tokenizer over pretty-printed JSON, adapted from the shared component library's JSON block. Read-only display, not a parser.
const TOKEN_RE = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(\btrue\b|\bfalse\b|\bnull\b)|([{}[\],])/g;

function tokenize(text: string): Token[] {
  const tokens: Token[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) tokens.push({ text: text.slice(last, m.index), cls: '' });
    if (m[1] !== undefined && m[2] !== undefined) {
      tokens.push({ text: m[1], cls: 'font-medium text-foreground' });
      tokens.push({ text: m[2], cls: 'text-muted-foreground' });
    } else if (m[1] !== undefined) {
      // Masked values stand out so a reader never mistakes them for data.
      tokens.push({ text: m[1], cls: m[1] === `"${REDACTED}"` ? 'rounded-sm bg-warning/20 px-0.5 text-warning-text' : 'text-success-text' });
    } else if (m[3] !== undefined) tokens.push({ text: m[3], cls: 'text-warning-text' });
    else if (m[4] !== undefined) tokens.push({ text: m[4], cls: 'italic text-foreground' });
    else if (m[5] !== undefined) tokens.push({ text: m[5], cls: 'text-muted-foreground' });
    last = TOKEN_RE.lastIndex;
  }
  if (last < text.length) tokens.push({ text: text.slice(last), cls: '' });
  return tokens;
}

/**
 * Read-only code block for request and response payloads, coloured from theme tokens so it follows light and dark.
 * Every token colour is above 4.5:1 on `bg-muted` in both themes (foreground, muted-foreground, success-text,
 * warning-text). Content scrolls inside the block so it never widens the sheet it sits in.
 */
export function JsonBlock({ value, tone = 'default', maxHeight = '16rem', wrap }: { value: unknown; tone?: 'default' | 'error'; maxHeight?: string; /** Wrap long lines instead of scrolling sideways. */ wrap?: boolean }) {
  const text = useMemo(() => (typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? ''), [value]);
  const tokens = useMemo(() => tokenize(text), [text]);
  return (
    <div className="group relative min-w-0" data-testid="json-block">
      <pre className={cn('overflow-auto rounded-md border bg-muted p-3 font-mono text-[12px] leading-relaxed text-foreground', tone === 'error' && 'border-destructive/50', wrap && 'break-words whitespace-pre-wrap')} style={{ maxHeight }}>
        <code>
          {tokens.map((t, i) => (
            <span key={i} className={t.cls || undefined}>
              {t.text}
            </span>
          ))}
        </code>
      </pre>
      <div className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <CopyButton text={text} className="text-muted-foreground hover:bg-accent hover:text-accent-foreground" />
      </div>
    </div>
  );
}
