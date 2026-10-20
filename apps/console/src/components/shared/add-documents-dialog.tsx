'use client';

import * as React from 'react';

import { PURPOSE_LABEL } from '@/components/files/file-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FilePicker } from '@/components/shared/file-picker';
import { FormField } from '@/components/shared/form-field';
import { FileUpload } from '@/components/shared/file-upload';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useUploadLimits, type UploadItem } from '@/hooks/file-queries';
import { plural } from '@/lib/format';
import type { FilePurpose } from '@/lib/types/files';

/**
 * Add documents by uploading new files or picking ones already in Files (c-159). An upload goes to Files first, so
 * both ways end as file ids handed to `onSubmit`; the caller adds them to its record. Used by a knowledge base's
 * Sources tab; any page that attaches stored files can use it the same way. Without a `purpose` the person chooses one
 * of the purposes storage settings accept uploads for, and its limits apply; `pick={false}` offers upload only.
 */
export function AddDocumentsDialog({
  open,
  onOpenChange,
  title = 'Add documents',
  description,
  purpose: fixedPurpose,
  pick = true,
  noun = 'document',
  isPending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title?: string;
  description: string;
  purpose?: FilePurpose;
  pick?: boolean;
  noun?: string;
  isPending: boolean;
  onSubmit: (fileIds: string[]) => Promise<unknown>;
}) {
  const limits = useUploadLimits();
  const purposes = (limits.data?.perPurpose ?? []).map((l) => l.purpose);
  const [chosen, setChosen] = React.useState<FilePurpose>();
  const purpose = fixedPurpose ?? chosen ?? purposes[0];
  const [uploads, setUploads] = React.useState<UploadItem[]>([]);
  const [picked, setPicked] = React.useState<string[]>([]);
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) {
      setUploads([]);
      setPicked([]);
      setChosen(undefined);
      setError(undefined);
    }
  }, [open]);

  const uploaded = uploads.flatMap((u) => (u.phase === 'ready' && u.fileId ? [u.fileId] : []));
  const busy = uploads.some((u) => u.phase === 'hashing' || u.phase === 'uploading' || u.phase === 'scanning');
  const ids = [...new Set([...uploaded, ...picked])];

  const submit = async () => {
    setError(undefined);
    try {
      await onSubmit(ids);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={title}
      description={description}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {error && <p className="mr-auto text-xs text-destructive">{error}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton isLoading={isPending} disabled={busy || !ids.length} onClick={submit} data-testid="add-documents-submit">
            {ids.length ? `Add ${plural(ids.length, noun)}` : `Add ${noun}s`}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {!fixedPurpose && (
          <FormField id="add-documents-purpose" label="Purpose" hint="Sets which types and sizes are accepted, and how long the files are kept.">
            <Select value={purpose} onValueChange={(v) => setChosen(v as FilePurpose)} disabled={uploads.length > 0}>
              <SelectTrigger id="add-documents-purpose" className="w-full bg-card" data-testid="add-documents-purpose">
                <SelectValue placeholder={limits.isPending ? 'Loading purposes…' : 'Choose a purpose'} />
              </SelectTrigger>
              <SelectContent>
                {purposes.map((p) => (
                  <SelectItem key={p} value={p}>
                    {PURPOSE_LABEL[p]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
        {/* Keyed on the purpose: a new purpose starts a new upload under its own limits. */}
        {purpose && <FileUpload key={purpose} purpose={purpose} multiple onChange={setUploads} title="Upload new files" testId="add-documents-upload" />}
        {pick && (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium">Or pick from Files</p>
            <FilePicker value={picked} onChange={setPicked} />
          </div>
        )}
      </div>
    </DialogShell>
  );
}
