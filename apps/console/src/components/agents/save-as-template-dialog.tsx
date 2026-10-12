'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { TemplateCategory, TemplateSubmissionInput } from '@/lib/types/templates';

import { CATEGORY_ORDER } from './template-meta';

/**
 * Offers the agent's current saved version as a template. It goes to the platform team for review and is
 * visible only to the submitting team until it is published.
 */
export function SaveAsTemplateDialog({
  open,
  onOpenChange,
  agentId,
  agentName,
  version,
  dirty,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: string;
  agentName: string;
  version: number;
  /** Unsaved edits on the page are not part of the submission. */
  dirty: boolean;
  onSubmit: (input: TemplateSubmissionInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [v, setV] = React.useState({ name: '', category: '' as TemplateCategory | '', summary: '', note: '' });
  const [touched, setTouched] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setV({ name: agentName, category: '', summary: '', note: '' });
    setTouched(false);
    setError(null);
  }, [open, agentName]);
  const errors = {
    name: v.name.trim().length < 2 ? 'Name the template, e.g. Hardship reply drafting.' : undefined,
    category: v.category ? undefined : 'Choose a category.',
    summary: v.summary.trim().length < 10 ? 'Say in one line what the template does.' : v.summary.length > 160 ? 'Keep the summary under 160 characters.' : undefined,
  };
  const e = (k: keyof typeof errors) => (touched ? errors[k] : undefined);
  const submit = async () => {
    setTouched(true);
    if (Object.values(errors).some(Boolean) || !v.category) return;
    try {
      await onSubmit({ agentId, name: v.name.trim(), category: v.category, summary: v.summary.trim(), note: v.note.trim() });
      onOpenChange(false);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Save as template"
      description={`Sends ${agentName} v${version} to the platform team for review. Other teams see it once it is published.`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton isLoading={isPending} loadingText="Sending…" onClick={submit}>
            Send for review
          </LoadingButton>
        </div>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(ev) => {
          ev.preventDefault();
          void submit();
        }}
      >
        {error && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
        {dirty && <p className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning-text">Unsaved changes on this page are not included. Save first to include them.</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="st-name" label="Template name" error={e('name')}>
            <Input id="st-name" value={v.name} onChange={(x) => setV({ ...v, name: x.target.value })} aria-invalid={!!e('name')} />
          </FormField>
          <FormField id="st-cat" label="Category" error={e('category')}>
            <Select value={v.category} onValueChange={(c) => setV({ ...v, category: c as TemplateCategory })}>
              <SelectTrigger id="st-cat" className="w-full" aria-invalid={!!e('category')}>
                <SelectValue placeholder="Choose a category" />
              </SelectTrigger>
              <SelectContent>
                {CATEGORY_ORDER.filter((c) => c !== 'Start from scratch').map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField id="st-summary" label="Summary" error={e('summary')} hint={`${v.summary.length} / 160 · shown on the template card.`}>
          <Input id="st-summary" value={v.summary} onChange={(x) => setV({ ...v, summary: x.target.value })} placeholder="e.g. Drafts hardship replies with the hardship line first" aria-invalid={!!e('summary')} />
        </FormField>
        <FormField id="st-note" label="Note to the reviewer" optional>
          <Textarea id="st-note" rows={3} value={v.note} onChange={(x) => setV({ ...v, note: x.target.value })} placeholder="e.g. Used by Lending Ops for six weeks; 96% of drafts approved unchanged" />
        </FormField>
        <p className="text-xs text-muted-foreground">Instructions, tools, knowledge and guardrails are copied. Customer data and eval results are not.</p>
        <button type="submit" hidden />
      </form>
    </DialogShell>
  );
}
