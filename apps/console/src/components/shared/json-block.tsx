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
      tokens.push({ text: m[1], cls: 'text-sky-300' });
      tokens.push({ text: m[2], cls: 'text-slate-500' });
    } else if (m[1] !== undefined) {
      // Masked values stand out so a reader never mistakes them for data.
      tokens.push({ text: m[1], cls: m[1] === `"${REDACTED}"` ? 'rounded-sm bg-amber-400/20 px-0.5 text-amber-300' : 'text-emerald-300' });
    } else if (m[3] !== undefined) tokens.push({ text: m[3], cls: 'text-amber-300' });
    else if (m[4] !== undefined) tokens.push({ text: m[4], cls: 'text-violet-300' });
    else if (m[5] !== undefined) tokens.push({ text: m[5], cls: 'text-slate-500' });
    last = TOKEN_RE.lastIndex;
  }
  if (last < text.length) tokens.push({ text: text.slice(last), cls: '' });
  return tokens;
}

/**
 * Dark read-only code block for request and response payloads. Content scrolls inside the block so it never widens
 * the sheet it sits in.
 */
export function JsonBlock({ value, tone = 'default', maxHeight = '16rem', wrap }: { value: unknown; tone?: 'default' | 'error'; maxHeight?: string; /** Wrap long lines instead of scrolling sideways. */ wrap?: boolean }) {
  const text = useMemo(() => (typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? ''), [value]);
  const tokens = useMemo(() => tokenize(text), [text]);
  return (
    <div className="group relative min-w-0" data-testid="json-block">
      <pre className={cn('overflow-auto rounded-md border bg-slate-950 p-3 font-mono text-[12px] leading-relaxed text-slate-200', tone === 'error' ? 'border-destructive/50' : 'border-slate-800', wrap && 'break-words whitespace-pre-wrap')} style={{ maxHeight }}>
        <code>
          {tokens.map((t, i) => (
            <span key={i} className={t.cls || undefined}>
              {t.text}
            </span>
          ))}
        </code>
      </pre>
      <div className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <CopyButton text={text} className="text-slate-300 hover:bg-slate-800 hover:text-white" />
      </div>
    </div>
  );
}
