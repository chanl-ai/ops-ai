'use client';

import * as React from 'react';

import { PageFields } from '@/components/knowledge/page-fields';
import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';

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
        <PageFields idPrefix="page" title={title} text={text} onTitle={setTitle} onText={setText} textError={error} autoFocus />
      </div>
    </DialogShell>
  );
}
