'use client';

import * as React from 'react';

import { Textarea } from '@/components/ui/textarea';

/** A JSON value typed as text: each edit that parses is passed on, one that does not says so and keeps the last. */
export function JsonInput({ id, value, onChange, rows = 5, placeholder = 'e.g. {"type": "object"}' }: { id: string; value: unknown; onChange: (v: unknown) => void; rows?: number; placeholder?: string }) {
  const show = (v: unknown) => (v === undefined ? '' : JSON.stringify(v, null, 2));
  const [text, setText] = React.useState(() => show(value));
  const [error, setError] = React.useState<string>();
  return (
    <div className="flex flex-col gap-1">
      <Textarea
        id={id}
        value={text}
        rows={rows}
        spellCheck={false}
        className="font-mono text-xs"
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) {
            setError(undefined);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(e.target.value));
            setError(undefined);
          } catch {
            setError('Not valid JSON yet');
          }
        }}
        data-field={id}
      />
      {error && <p className="text-xs text-destructive-text">{error}</p>}
    </div>
  );
}
