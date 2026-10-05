'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { AccessOptions, GrantInput, ResourceKind } from '@/lib/types/governance';

import { RESOURCE_KIND_LABEL, SCOPE_LABEL, ScopeBadge } from './access-meta';

const EXPIRY = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '180', label: '180 days' },
  { value: '365', label: '365 days' },
];

/** Grants one workflow identity access to one system module or knowledge base. The scope follows the module. */
export function GrantDialog({
  open,
  onOpenChange,
  options,
  defaultWorkflowId,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  options?: AccessOptions;
  defaultWorkflowId?: string;
  onSubmit: (input: GrantInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [workflowId, setWorkflowId] = React.useState('');
  const [kind, setKind] = React.useState<ResourceKind>('module');
  const [resource, setResource] = React.useState('');
  const [expiry, setExpiry] = React.useState('90');
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState<{ field?: string; message: string } | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setWorkflowId(defaultWorkflowId ?? '');
    setKind('module');
    setResource('');
    setExpiry('90');
    setReason('');
    setError(null);
  }, [open, defaultWorkflowId]);

  const mod = options?.modules.find((m) => m.value === resource);
  const scope = kind === 'knowledge_base' ? 'read' : (mod?.access ?? 'read');
  const money = scope === 'money_movement';
  const systems = [...new Set(options?.modules.map((m) => m.system) ?? [])];

  const submit = async () => {
    if (!workflowId) return setError({ field: 'workflow', message: 'Choose a workflow.' });
    if (!resource) return setError({ field: 'resource', message: `Choose a ${kind === 'module' ? 'module' : 'knowledge base'}.` });
    if (!expiry) return setError({ field: 'expiry', message: 'Choose when the access expires.' });
    if (money && Number(expiry) > 180) return setError({ field: 'expiry', message: 'Money-movement access must expire within 180 days.' });
    if (money && !reason.trim()) return setError({ field: 'reason', message: 'Give the approval reference, e.g. the model risk committee decision.' });
    try {
      await onSubmit({ workflowId, resourceKind: kind, resource, scope, expiresInDays: Number(expiry), reason });
      onOpenChange(false);
    } catch (e) {
      setError({ message: (e as Error).message });
    }
  };

  const fieldError = (f: string) => (error?.field === f ? error.message : undefined);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Grant access"
      description="The workflow’s identity can call this from its next run. Every call is still checked against gates."
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <p className="text-xs text-destructive">{error && !error.field ? error.message : ''}</p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
              Cancel
            </Button>
            <LoadingButton isLoading={isPending} onClick={submit}>
              Grant access
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="grant-workflow" label="Workflow" error={fieldError('workflow')}>
          <Select value={workflowId} onValueChange={(v) => (setWorkflowId(v), setError(null))}>
            <SelectTrigger id="grant-workflow" className="w-full" aria-invalid={!!fieldError('workflow')}>
              <SelectValue placeholder="Choose a workflow" />
            </SelectTrigger>
            <SelectContent>
              {options?.workflows.map((w) => (
                <SelectItem key={w.id} value={w.id}>
                  {w.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        <div className="flex flex-col gap-1.5">
          <Label>Access to</Label>
          <RadioGroup
            value={kind}
            onValueChange={(v) => {
              setKind(v as ResourceKind);
              setResource('');
              setError(null);
            }}
            className="flex gap-4"
          >
            {(Object.keys(RESOURCE_KIND_LABEL) as ResourceKind[]).map((k) => (
              <div key={k} className="flex items-center gap-2">
                <RadioGroupItem value={k} id={`grant-kind-${k}`} />
                <Label htmlFor={`grant-kind-${k}`} className="font-normal">
                  {RESOURCE_KIND_LABEL[k]}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>

        <FormField
          id="grant-resource"
          label={kind === 'module' ? 'Module' : 'Knowledge base'}
          error={fieldError('resource')}
          hint={resource ? <span className="inline-flex items-center gap-1.5">Scope <ScopeBadge scope={scope} /> {kind === 'module' ? 'set by the module' : 'knowledge bases are read only'}</span> : undefined}
        >
          <Select value={resource} onValueChange={(v) => (setResource(v), setError(null))}>
            <SelectTrigger id="grant-resource" className="w-full" aria-invalid={!!fieldError('resource')}>
              <SelectValue placeholder={kind === 'module' ? 'Choose a module' : 'Choose a knowledge base'} />
            </SelectTrigger>
            <SelectContent>
              {kind === 'module'
                ? systems.map((s) => (
                    <SelectGroup key={s}>
                      <SelectLabel>{s}</SelectLabel>
                      {options!.modules
                        .filter((m) => m.system === s)
                        .map((m) => (
                          <SelectItem key={m.value} value={m.value}>
                            <span className="font-mono text-[13px]">{m.value.split(' · ')[1]}</span>
                            <span className="text-xs text-muted-foreground">{SCOPE_LABEL[m.access]}</span>
                          </SelectItem>
                        ))}
                    </SelectGroup>
                  ))
                : options?.knowledgeBases.map((k) => (
                    <SelectItem key={k} value={k}>
                      {k}
                    </SelectItem>
                  ))}
            </SelectContent>
          </Select>
        </FormField>

        <FormField id="grant-expiry" label="Expires" error={fieldError('expiry')} hint={money ? 'Money-movement access expires within 180 days and is renewed on re-approval.' : 'Every grant expires. Extend it before then if the workflow still needs it.'}>
          <Select value={expiry} onValueChange={(v) => (setExpiry(v), setError(null))}>
            <SelectTrigger id="grant-expiry" className="w-full" aria-invalid={!!fieldError('expiry')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {EXPIRY.map((e) => (
                <SelectItem key={e.value} value={e.value} disabled={money && Number(e.value) > 180}>
                  {e.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        <FormField id="grant-reason" label="Reason" optional={!money} error={fieldError('reason')}>
          <Textarea id="grant-reason" value={reason} onChange={(e) => (setReason(e.target.value), setError(null))} placeholder="e.g. Approved by the model risk committee, decision MRC-000" rows={2} aria-invalid={!!fieldError('reason')} />
        </FormField>
      </div>
    </DialogShell>
  );
}
