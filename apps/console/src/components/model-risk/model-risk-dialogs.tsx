'use client';

import * as React from 'react';

import { SelectedList } from '@/components/shared/bulk';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { Risk } from '@/lib/types/domain';
import type { ConditionInput } from '@/lib/types/model-risk';

const TIERS: { value: Risk; label: string; hint: string }[] = [
  { value: 'low', label: 'Low', hint: 'No money movement; every write needs an approval token.' },
  { value: 'medium', label: 'Medium', hint: 'Writes that a person approves; customer-facing drafts.' },
  { value: 'high', label: 'High', hint: 'Money movement or decisions customers rely on.' },
  { value: 'critical', label: 'Critical', hint: 'Money movement at scale, or regulatory decisions.' },
];
const isHigh = (t: Risk) => t === 'high' || t === 'critical';
const today = () => new Date().toISOString().slice(0, 10);

function Footer({ onCancel, pending, onConfirm, label, disabled }: { onCancel: () => void; pending: boolean; onConfirm: () => void; label: string; disabled?: boolean }) {
  return (
    <div className="flex w-full justify-end gap-2">
      <Button variant="outline" onClick={onCancel} disabled={pending}>
        Cancel
      </Button>
      <LoadingButton isLoading={pending} onClick={onConfirm} disabled={disabled}>
        {label}
      </LoadingButton>
    </div>
  );
}

/** Change a model's tier. Changes to or from high and critical go to Model Risk as a second-line review. */
export function TierDialog({ open, onOpenChange, name, current, onSubmit, isPending }: { open: boolean; onOpenChange: (o: boolean) => void; name: string; current: Risk; onSubmit: (tier: Risk, reason: string) => Promise<unknown>; isPending: boolean }) {
  const [tier, setTier] = React.useState<Risk>(current);
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState<{ tier?: string; reason?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setTier(current);
      setReason('');
      setError({});
    }
  }, [open, current]);
  const needsApproval = tier !== current && (isHigh(tier) || isHigh(current));
  const submit = async () => {
    const e = { tier: tier === current ? `Already ${current}. Choose another tier.` : undefined, reason: reason.trim() ? undefined : 'Say why the tier changes. It is recorded in the audit log.' };
    setError(e);
    if (e.tier || e.reason) return;
    try {
      await onSubmit(tier, reason.trim());
      onOpenChange(false);
    } catch (err) {
      setError({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={`Change tier of ${name}`}
      description="The tier sets the publish gate: the injection threshold, which test failures block, and whether Model Risk must approve."
      footer={<Footer onCancel={() => onOpenChange(false)} pending={isPending} onConfirm={submit} label={needsApproval ? 'Send to Model Risk' : 'Change tier'} />}
    >
      <div className="flex flex-col gap-4">
        <FormField id="tier" label="Tier" error={error.tier} hint={TIERS.find((t) => t.value === tier)?.hint}>
          <Select value={tier} onValueChange={(v) => (setTier(v as Risk), setError({ ...error, tier: undefined }))}>
            <SelectTrigger id="tier" className="w-full" aria-invalid={!!error.tier}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TIERS.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                  {t.value === current ? ' (current)' : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="tier-reason" label="Reason" error={error.reason}>
          <Textarea id="tier-reason" aria-invalid={!!error.reason} value={reason} onChange={(e) => (setReason(e.target.value), setError({ ...error, reason: undefined }))} placeholder="e.g. Now posts provisional credit without a person for amounts under $200" className="min-h-20" />
        </FormField>
        {needsApproval && (
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            A change to or from high or critical needs second-line approval. It opens a review for Model Risk and applies when they approve.
          </p>
        )}
        {error.submit && <p className="text-sm text-destructive">{error.submit}</p>}
      </div>
    </DialogShell>
  );
}

/** Add a condition on the model's use, with an owner and a due date. */
export function ConditionDialog({ open, onOpenChange, owners, onSubmit, isPending }: { open: boolean; onOpenChange: (o: boolean) => void; owners: string[]; onSubmit: (c: ConditionInput) => Promise<unknown>; isPending: boolean }) {
  const [v, setV] = React.useState<ConditionInput>({ text: '', owner: '', dueDate: '' });
  const [error, setError] = React.useState<Partial<Record<keyof ConditionInput | 'submit', string>>>({});
  React.useEffect(() => {
    if (open) {
      setV({ text: '', owner: '', dueDate: '' });
      setError({});
    }
  }, [open]);
  const submit = async () => {
    const e = { text: v.text.trim() ? undefined : 'Describe the condition.', owner: v.owner ? undefined : 'Choose who answers for it.', dueDate: v.dueDate ? (v.dueDate < today() ? 'Choose today or later.' : undefined) : 'Choose a due date.' };
    setError(e);
    if (e.text || e.owner || e.dueDate) return;
    try {
      await onSubmit({ ...v, text: v.text.trim() });
      onOpenChange(false);
    } catch (err) {
      setError({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell open={open} onOpenChange={onOpenChange} size="md" title="Add condition" description="A condition limits how the model may be used until it is met. Changes are audited." footer={<Footer onCancel={() => onOpenChange(false)} pending={isPending} onConfirm={submit} label="Add condition" />}>
      <div className="flex flex-col gap-4">
        <FormField id="cnd-text" label="Condition" error={error.text}>
          <Textarea id="cnd-text" aria-invalid={!!error.text} value={v.text} onChange={(e) => (setV({ ...v, text: e.target.value }), setError({ ...error, text: undefined }))} placeholder="e.g. Human approval on all writes until 2026-12-31" className="min-h-16" />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="cnd-owner" label="Owner" error={error.owner}>
            <Select value={v.owner} onValueChange={(owner) => (setV({ ...v, owner }), setError({ ...error, owner: undefined }))}>
              <SelectTrigger id="cnd-owner" className="w-full" aria-invalid={!!error.owner}>
                <SelectValue placeholder="Choose a team" />
              </SelectTrigger>
              <SelectContent>
                {owners.map((o) => (
                  <SelectItem key={o} value={o}>
                    {o}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="cnd-due" label="Due date" error={error.dueDate}>
            <Input id="cnd-due" type="date" min={today()} aria-invalid={!!error.dueDate} value={v.dueDate} onChange={(e) => (setV({ ...v, dueDate: e.target.value }), setError({ ...error, dueDate: undefined }))} />
          </FormField>
        </div>
        {error.submit && <p className="text-sm text-destructive">{error.submit}</p>}
      </div>
    </DialogShell>
  );
}

/** Mark a condition met or reopen it; the reason goes into the audit log. */
export function ConditionStatusDialog({ open, onOpenChange, text, next, onSubmit, isPending }: { open: boolean; onOpenChange: (o: boolean) => void; text: string; next: 'met' | 'open'; onSubmit: (reason: string) => Promise<unknown>; isPending: boolean }) {
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setReason('');
      setError(null);
    }
  }, [open]);
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={next === 'met' ? 'Mark condition met' : 'Reopen condition'}
      description={next === 'met' ? 'The model is no longer bound by it.' : 'The model is bound by it again until it is met.'}
      footer={
        <Footer
          onCancel={() => onOpenChange(false)}
          pending={isPending}
          label={next === 'met' ? 'Mark met' : 'Reopen'}
          onConfirm={async () => {
            if (!reason.trim()) return setError('Give a reason. It is recorded in the audit log.');
            try {
              await onSubmit(reason.trim());
              onOpenChange(false);
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        />
      }
    >
      <div className="flex flex-col gap-3">
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm">{text}</p>
        <FormField id="cnd-reason" label="Reason" error={error ?? undefined}>
          <Textarea id="cnd-reason" aria-invalid={!!error} value={reason} onChange={(e) => (setReason(e.target.value), setError(null))} placeholder="e.g. Fraud QA sampled 50 released holds in September" className="min-h-16" />
        </FormField>
      </div>
    </DialogShell>
  );
}

/** Bulk: open a validation review for each selected model. */
export function RequestValidationDialog({ open, onOpenChange, names, onSubmit, isPending }: { open: boolean; onOpenChange: (o: boolean) => void; names: string[]; onSubmit: (note: string) => Promise<unknown>; isPending: boolean }) {
  const [note, setNote] = React.useState('');
  React.useEffect(() => {
    if (open) setNote('');
  }, [open]);
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={names.length === 1 ? `Request validation of ${names[0]}` : `Request validation of ${names.length} models`}
      description="Each one goes to Model Risk as a review. Models that already have a validation open are skipped."
      footer={
        <Footer
          onCancel={() => onOpenChange(false)}
          pending={isPending}
          label="Request validation"
          onConfirm={async () => {
            await onSubmit(note.trim());
            onOpenChange(false);
          }}
        />
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="rv-note" label="Note to the validator" optional>
          <Textarea id="rv-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. New money-movement step added in v8" className="min-h-16" />
        </FormField>
        <SelectedList names={names} />
      </div>
    </DialogShell>
  );
}

/** Bulk: set the next review date. */
export function NextReviewDialog({ open, onOpenChange, names, onSubmit, isPending }: { open: boolean; onOpenChange: (o: boolean) => void; names: string[]; onSubmit: (date: string) => Promise<unknown>; isPending: boolean }) {
  const [date, setDate] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setDate('');
      setError(null);
    }
  }, [open]);
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={names.length === 1 ? `Set next review of ${names[0]}` : `Set next review of ${names.length} models`}
      description="Model Risk is reminded 30 days before. Validations past this date show as expired."
      footer={
        <Footer
          onCancel={() => onOpenChange(false)}
          pending={isPending}
          label="Set date"
          onConfirm={async () => {
            if (!date) return setError('Choose a date.');
            if (date < today()) return setError('Choose today or later.');
            try {
              await onSubmit(date);
              onOpenChange(false);
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        />
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="nr-date" label="Next review" error={error ?? undefined}>
          <Input id="nr-date" type="date" min={today()} aria-invalid={!!error} value={date} onChange={(e) => (setDate(e.target.value), setError(null))} />
        </FormField>
        <SelectedList names={names} />
      </div>
    </DialogShell>
  );
}
