'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import type { KnowledgeBaseInput, RetrievalPreset } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

const PRESETS: { value: RetrievalPreset; label: string; description: string }[] = [
  { value: 'balanced', label: 'Balanced', description: 'Keyword search, 8 chunks, threshold 0.50, answer synthesis on. A good default for policy and product content.' },
  { value: 'precise', label: 'Precise', description: 'Keyword search, 5 chunks, threshold 0.65, temperature 0. Fewer answers, fewer wrong ones. For fees, limits and regulated wording.' },
  { value: 'raw', label: 'Raw retrieval', description: 'Keyword search, 10 chunks, threshold 0.40, no synthesis. Returns chunks only, for an agent to answer from.' },
];

/**
 * New knowledge base in one screen: name, its owner, an optional description and a retrieval preset. It needs no
 * source; the page's Sources tab attaches one, and the first index build starts once it has a source.
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
  onSubmit: (input: KnowledgeBaseInput) => Promise<unknown>;
}) {
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [owner, setOwner] = React.useState(defaultOwner);
  const [preset, setPreset] = React.useState<RetrievalPreset>('balanced');
  const [errors, setErrors] = React.useState<{ name?: string; owner?: string; description?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setName('');
      setDescription('');
      setOwner(defaultOwner);
      setPreset('balanced');
      setErrors({});
    }
  }, [open, defaultOwner]);

  const submit = async () => {
    const e = {
      name:
        name.trim().length < 2 || name.length > 80
          ? 'Name it in 2 to 80 characters, e.g. Card disputes.'
          : existingNames.some((n) => n.toLowerCase() === name.trim().toLowerCase())
            ? 'A knowledge base with this name already exists.'
            : undefined,
      owner: /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(owner.trim()) ? undefined : 'Enter the owner’s email, e.g. j.richardson@example.com.',
      description: description.length > 500 ? 'Keep the description under 500 characters.' : undefined,
    };
    setErrors(e);
    if (e.name || e.owner || e.description) return;
    try {
      await onSubmit({ name: name.trim(), owner: owner.trim(), description: description.trim(), color: 'teal', sourceIds: [], preset, collections: [] });
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New knowledge base"
      description="Attach sources on the next page. The first index build starts once it has a source."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton isLoading={isPending} onClick={submit} data-testid="kb-create">
            Create knowledge base
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="kb-name" label="Name" error={errors.name}>
          <Input id="kb-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Card disputes" autoFocus aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="kb-owner" label="Owner" hint="The person who answers for what it serves. They or a tenant admin can change it." error={errors.owner}>
          <Input id="kb-owner" type="email" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="e.g. j.richardson@example.com" aria-invalid={!!errors.owner} />
        </FormField>
        <FormField id="kb-desc" label="Description" optional hint={`${description.length} / 500 · agents see this when choosing what to search.`} error={errors.description}>
          <Textarea id="kb-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Dispute reason codes, chargeback timelines and provisional credit rules" aria-invalid={!!errors.description} />
        </FormField>
        <FormField id="kb-preset" label="Retrieval preset" hint="Every setting can be changed later on the Retrieval tab.">
          <RadioGroup value={preset} onValueChange={(p) => setPreset(p as RetrievalPreset)} className="grid gap-2">
            {PRESETS.map((p) => (
              <label key={p.value} htmlFor={`kb-preset-${p.value}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', preset === p.value && 'border-primary bg-primary/5')}>
                <RadioGroupItem value={p.value} id={`kb-preset-${p.value}`} className="mt-0.5" />
                <span>
                  <span className="block text-sm font-medium">{p.label}</span>
                  <span className="block text-xs text-muted-foreground">{p.description}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
        </FormField>
      </div>
    </DialogShell>
  );
}
