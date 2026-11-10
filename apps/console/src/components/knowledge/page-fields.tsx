'use client';

import { FormField } from '@/components/shared/form-field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

/** A page as typed text: its title and its Markdown, where a `##` heading starts a section that citations name. */
export function PageFields({ idPrefix, title, text, onTitle, onText, titleError, textError, autoFocus }: { idPrefix: string; title: string; text: string; onTitle: (v: string) => void; onText: (v: string) => void; titleError?: string; textError?: string; autoFocus?: boolean }) {
  return (
    <>
      <FormField id={`${idPrefix}-title`} label="Title" error={titleError}>
        <Input id={`${idPrefix}-title`} value={title} onChange={(e) => onTitle(e.target.value)} placeholder="e.g. Cash drawer limits" maxLength={200} autoFocus={autoFocus} aria-invalid={!!titleError} data-testid={`${idPrefix}-title`} />
      </FormField>
      <FormField id={`${idPrefix}-text`} label="Text" hint="Markdown: a line starting with ## begins a section that citations name." error={textError}>
        <Textarea id={`${idPrefix}-text`} rows={10} value={text} onChange={(e) => onText(e.target.value)} className="font-mono text-sm" aria-invalid={!!textError} data-testid={`${idPrefix}-text`} />
      </FormField>
    </>
  );
}
