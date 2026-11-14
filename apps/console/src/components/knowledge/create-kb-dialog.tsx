'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Check } from 'lucide-react';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { UploadItem } from '@/hooks/file-queries';
import type { KnowledgeBaseInput, RetrievalPreset } from '@/lib/types/knowledge';

/**
 * What each preset fills, as kb-service's PRESETS and DEFAULT_SETTINGS (services/kb-service/src/ops_kb/service.py)
 * hold them; that file is the one source, and these lines say it back. The base does not remember its preset.
 */
const PRESETS: { value: RetrievalPreset; label: string; use: string; fills: string[] }[] = [
  {
    value: 'balanced',
    label: 'Balanced',
    use: 'Policy, product and procedure content. A good default.',
    fills: ['Meaning and keyword, weight 0.6', '8 pieces; floors 0.50 keyword, 0.38 meaning', 'Gives back an answer with citations, withheld when uncited', 'New sources split at headings, 400 tokens'],
  },
  {
    value: 'precise',
    label: 'Precise',
    use: 'Fees, limits and regulated wording: fewer answers, fewer wrong ones.',
    fills: ['Meaning and keyword, weight 0.6', '5 pieces; floors 0.65 keyword, 0.45 meaning', 'Gives back an answer with citations, withheld when uncited', 'New sources split at headings, 400 tokens'],
  },
  {
    value: 'raw',
    label: 'Search only',
    use: 'An agent or workflow answers from the pieces itself.',
    fills: ['Meaning and keyword, weight 0.6', '10 pieces; floors 0.40 keyword, 0.30 meaning', 'Gives back pieces only, no answer', 'New sources split at headings, 400 tokens'],
  },
];

const schemaFor = (existing: string[], ownerShown: boolean) =>
  z.object({
    name: z
      .string()
      .trim()
      .min(2, 'Name it in 2 to 80 characters, e.g. Card disputes.')
      .max(80, 'Name it in 2 to 80 characters, e.g. Card disputes.')
      .refine((n) => !existing.some((e) => e.toLowerCase() === n.toLowerCase()), 'A knowledge base with this name already exists.'),
    owner: ownerShown ? z.string().trim().email('Enter the owner’s email, e.g. j.richardson@example.com.') : z.string(),
    description: z.string().max(500, 'Keep the description under 500 characters.'),
    preset: z.enum(['balanced', 'precise', 'raw']),
  });
type Values = { name: string; owner: string; description: string; preset: RetrievalPreset };

/**
 * New knowledge base in one screen: its name, an optional description, files to index straight away, and the preset
 * that fills its settings as a starting point. Every value stays editable on the Settings tab. Uploaded files go to
 * Files first; the caller adds them to the base once it exists.
 */
export function CreateKbDialog({
  open,
  onOpenChange,
  existingNames,
  isPending,
  defaultOwner,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existingNames: string[];
  isPending: boolean;
  /** The signed-in person's email. */
  defaultOwner: string;
  onSubmit: (input: KnowledgeBaseInput, fileIds: string[]) => Promise<unknown>;
}) {
  const schema = React.useMemo(() => schemaFor(existingNames, !defaultOwner), [existingNames, defaultOwner]);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: '', owner: defaultOwner, description: '', preset: 'balanced' } });
  const { register, control, handleSubmit, reset, watch, formState, setError } = form;
  const [uploads, setUploads] = React.useState<UploadItem[]>([]);
  const [uploadKey, setUploadKey] = React.useState(0);
  React.useEffect(() => {
    if (open) {
      reset({ name: '', owner: defaultOwner, description: '', preset: 'balanced' });
      setUploads([]);
      setUploadKey((k) => k + 1);
    }
  }, [open, defaultOwner, reset]);
  const fileIds = uploads.flatMap((u) => (u.phase === 'ready' && u.fileId ? [u.fileId] : []));
  const uploading = uploads.some((u) => u.phase === 'hashing' || u.phase === 'uploading' || u.phase === 'scanning');
  const description = watch('description');

  const submit = handleSubmit(async (v) => {
    try {
      await onSubmit({ name: v.name.trim(), owner: v.owner.trim(), description: v.description.trim(), color: 'teal', sourceIds: [], preset: v.preset, collections: [] }, fileIds);
    } catch (err) {
      setError('root', { message: (err as Error).message });
    }
  });

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="New knowledge base"
      description="A preset fills the settings below as a starting point. Every value stays editable on the Settings tab."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {formState.errors.root && <p className="mr-auto text-xs text-destructive-text">{formState.errors.root.message}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton isLoading={isPending} disabled={uploading} onClick={() => void submit()} data-testid="kb-create">
            Create knowledge base
          </LoadingButton>
        </div>
      }
    >
      <form className="flex flex-col gap-4" onSubmit={(e) => void submit(e)}>
        <FormField id="kb-name" label="Name" error={formState.errors.name?.message}>
          <Input id="kb-name" {...register('name')} placeholder="e.g. Card disputes" autoFocus aria-invalid={!!formState.errors.name} />
        </FormField>
        {/* The person creating it owns it; the field shows only when the session has no email to default to. */}
        {!defaultOwner && (
          <FormField id="kb-owner" label="Owner" hint="The person who answers for what it serves. They or a team admin can change it." error={formState.errors.owner?.message}>
            <Input id="kb-owner" type="email" {...register('owner')} placeholder="e.g. j.richardson@example.com" aria-invalid={!!formState.errors.owner} />
          </FormField>
        )}
        <FormField id="kb-desc" label="Description" optional hint={`${description.length} / 500 · agents see this when choosing what to search.`} error={formState.errors.description?.message}>
          <Textarea id="kb-desc" rows={2} {...register('description')} placeholder="e.g. Dispute reason codes, chargeback timelines and provisional credit rules" aria-invalid={!!formState.errors.description} />
        </FormField>
        <FormField id="kb-files" label="Files" optional hint="Indexed as soon as the base exists. Add websites and apps from its Sources tab.">
          <FileUpload key={uploadKey} id="kb-files" purpose="knowledge_source" multiple onChange={setUploads} title="Drop files here, or choose files" testId="kb-create-files" />
        </FormField>
        <FormField id="kb-preset" label="Start from" hint="The preset only fills values. Change any of them later on the Settings tab; the base does not remember which preset it started from.">
          <Controller
            control={control}
            name="preset"
            render={({ field }) => (
              <ChoiceCards
                name="kb-preset"
                label="Start from"
                columns={3}
                value={field.value}
                onChange={field.onChange}
                choices={PRESETS.map((p) => ({
                  value: p.value,
                  title: p.label,
                  description: (
                    <>
                      <span className="block">{p.use}</span>
                      <span className="mt-2 flex flex-col gap-1 border-t pt-2">
                        {p.fills.map((f) => (
                          <span key={f} className="flex items-start gap-1.5">
                            <Check className="mt-0.5 size-3 shrink-0" aria-hidden />
                            {f}
                          </span>
                        ))}
                      </span>
                    </>
                  ),
                }))}
              />
            )}
          />
        </FormField>
      </form>
    </DialogShell>
  );
}
