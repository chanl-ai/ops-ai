'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

/**
 * Write a page into a knowledge base: a title and its text, Markdown allowed (a `##` heading starts a section that
 * citations name). Saved under a title the base already has, it becomes that page's next version.
 */
export function AddPageDialog({ open, onOpenChange, onSubmit, saving }: { open: boolean; onOpenChange: (open: boolean) => void; onSubmit: (input: { title: string; text: string }) => Promise<unknown>; saving: boolean }) {
  const [title, setTitle] = React.useState('');
  const [text, setText] = React.useState('');
  const [error, setError] = React.useState<string | undefined>();
  React.useEffect(() => {
    if (open) {
      setTitle('');
      setText('');
      setError(undefined);
    }
  }, [open]);
  const submit = () => {
    if (!title.trim() || !text.trim()) return setError('Give the page a title and its text.');
    onSubmit({ title: title.trim(), text }).then(
      () => onOpenChange(false),
      (e: Error) => setError(e.message),
    );
  };
  return (
    <DialogShell
      open={open}
      onSubmit={submit}
      onOpenChange={onOpenChange}
      size="md"
      title="Add a page"
      description="Write it here; it is indexed at once and cited like any document."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={saving} loadingText="Indexing…">
            Add page
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="page-title" label="Title">
          <Input id="page-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Cash drawer limits" autoFocus />
        </FormField>
        <FormField id="page-text" label="Text" hint="Markdown: a line starting with ## begins a section that citations name." error={error}>
          <Textarea id="page-text" rows={10} value={text} onChange={(e) => setText(e.target.value)} className="font-mono text-sm" aria-invalid={!!error} />
        </FormField>
      </div>
    </DialogShell>
  );
}
