'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { AccessBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { ApprovalRequestInput, Environment, ModuleOperation } from '@/lib/types/tool-modules';

const EXPIRY: Record<Environment, number[]> = { production: [30, 90, 180, 365], test: [14, 30, 90], dev: [14, 30, 90] };

/** A workflow asks the module's owner team for some operations, for a fixed time. Money operations are flagged. */
export function RequestApprovalDialog({
  open,
  onOpenChange,
  workflows,
  operations,
  major,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflows: { id: string; name: string }[];
  operations: ModuleOperation[];
  major: number;
  onSubmit: (input: ApprovalRequestInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [workflowId, setWorkflowId] = React.useState('');
  const [environment, setEnvironment] = React.useState<Environment>('production');
  const [ops, setOps] = React.useState<Set<string>>(new Set());
  const [days, setDays] = React.useState('180');
  const [why, setWhy] = React.useState('');
  const [touched, setTouched] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setWorkflowId('');
    setEnvironment('production');
    setOps(new Set());
    setDays('180');
    setWhy('');
    setTouched(false);
    setError(null);
  }, [open]);

  const exposed = operations.filter((o) => o.enabled);
  const money = exposed.filter((o) => ops.has(o.name) && o.fourEyes);
  const errs = { workflow: !workflowId ? 'Choose a workflow.' : undefined, ops: !ops.size ? 'Choose at least one operation.' : undefined, why: why.trim().length < 10 ? 'Explain why the workflow needs these operations.' : undefined };
  const invalid = Object.values(errs).some(Boolean);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Request approval"
      description={`The module’s owner team decides. The approval covers major version ${major}; a new major needs a new approval.`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            loadingText="Requesting…"
            onClick={async () => {
              setTouched(true);
              setError(null);
              if (invalid) return;
              try {
                await onSubmit({ workflowId, environment, operations: [...ops], expiresInDays: Number(days), justification: why.trim() });
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Request approval
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {error && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="ra-wf" label="Workflow" error={touched ? errs.workflow : undefined}>
            <Select value={workflowId} onValueChange={setWorkflowId}>
              <SelectTrigger id="ra-wf" className="w-full" aria-invalid={touched && !!errs.workflow}>
                <SelectValue placeholder="Choose a workflow" />
              </SelectTrigger>
              <SelectContent>
                {workflows.map((w) => (
                  <SelectItem key={w.id} value={w.id}>
                    {w.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="ra-env" label="Environment">
            <Select
              value={environment}
              onValueChange={(v) => {
                setEnvironment(v as Environment);
                setDays(v === 'production' ? '180' : '30');
              }}
            >
              <SelectTrigger id="ra-env" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="production">Production</SelectItem>
                <SelectItem value="test">Test</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField id="ra-ops" label="Operations" error={touched ? errs.ops : undefined}>
          <div className="divide-y rounded-md border">
            {exposed.map((o) => (
              <label key={o.name} htmlFor={`ra-${o.name}`} className="flex cursor-pointer items-center gap-3 px-3 py-2">
                <Checkbox
                  id={`ra-${o.name}`}
                  checked={ops.has(o.name)}
                  onCheckedChange={(v) =>
                    setOps((s) => {
                      const n = new Set(s);
                      if (v) n.add(o.name);
                      else n.delete(o.name);
                      return n;
                    })
                  }
                />
                <code className="min-w-0 flex-1 truncate font-mono text-sm">{o.name}</code>
                <AccessBadge access={o.access} />
              </label>
            ))}
          </div>
        </FormField>
        {money.length > 0 && <p className="text-xs text-red-700 dark:text-red-400">{money.map((o) => o.name).join(', ')} moves money: every call still needs a person’s approval and a second person’s check.</p>}
        <FormField id="ra-exp" label="Expires after" hint={environment === 'production' ? 'Production approvals last at most 12 months.' : 'Test approvals last at most 90 days.'}>
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger id="ra-exp" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {EXPIRY[environment].map((d) => (
                <SelectItem key={d} value={String(d)}>
                  {d} days
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="ra-why" label="Justification" error={touched ? errs.why : undefined}>
          <Textarea id="ra-why" rows={3} value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. Read the loan account to answer payoff requests sent to the servicing mailbox" aria-invalid={touched && !!errs.why} />
        </FormField>
      </div>
    </DialogShell>
  );
}

/** Reject or revoke: both need a reason that lands in the audit log. */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  reasons,
  confirmLabel,
  destructive,
  onConfirm,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  reasons: string[];
  confirmLabel: string;
  destructive?: boolean;
  onConfirm: (reason: string) => Promise<unknown>;
  isPending: boolean;
}) {
  const [reason, setReason] = React.useState('');
  React.useEffect(() => {
    if (open) setReason('');
  }, [open]);
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={title}
      description={description}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton variant={destructive ? 'destructive' : 'default'} isLoading={isPending} disabled={!reason} onClick={() => onConfirm(reason)}>
            {confirmLabel}
          </LoadingButton>
        </div>
      }
    >
      <FormField id="reason" label="Reason">
        <Select value={reason} onValueChange={setReason}>
          <SelectTrigger id="reason" className="w-full">
            <SelectValue placeholder="Choose a reason" />
          </SelectTrigger>
          <SelectContent>
            {reasons.map((r) => (
              <SelectItem key={r} value={r}>
                {r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
    </DialogShell>
  );
}
