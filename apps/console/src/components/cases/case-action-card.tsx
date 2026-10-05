'use client';

import * as React from 'react';
import { Check, FileSearch, Mail, Pencil, ShieldCheck, Wrench, X } from 'lucide-react';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ActionStatusBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { relativeTime } from '@/lib/format';
import type { CaseAction } from '@/lib/types/cases';

const isPending = (a: CaseAction) => a.needsApproval && (a.status === 'drafted' || a.status === 'awaiting_second');

/**
 * One drafted action on a case. Each action is approved on its own, so a reply can go out while a refund
 * still waits for a second approver.
 */
export function CaseActionCard({
  action,
  currentUser,
  caseOpen,
  onApprove,
  onReject,
  onEdit,
  busy,
}: {
  action: CaseAction;
  currentUser?: string;
  caseOpen: boolean;
  onApprove: () => Promise<unknown>;
  onReject: (reason: string) => Promise<unknown>;
  onEdit: (input: string) => Promise<unknown>;
  busy: 'approve' | 'reject' | 'edit' | null;
}) {
  const [dialog, setDialog] = React.useState<'reject' | 'edit' | 'confirm' | null>(null);
  const pending = caseOpen && isPending(action);
  const iApproved = !!currentUser && action.approvals.some((x) => x.by === currentUser);
  const Icon = action.kind === 'reply' ? Mail : Wrench;

  return (
    <Card className={pending ? 'border-amber-500/40' : undefined} data-testid={`action-${action.id}`}>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2 space-y-0">
        <div className="flex min-w-0 items-start gap-2">
          <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <CardTitle className="text-sm font-medium">{action.label}</CardTitle>
            <p className="text-xs text-muted-foreground">{action.kind === 'reply' ? 'Email to the customer' : 'Tool call'}</p>
          </div>
        </div>
        <ActionStatusBadge status={action.status} needsApproval={action.needsApproval} />
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <pre className="max-h-64 overflow-auto rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap">{action.input}</pre>

        {action.evidence.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <FileSearch className="size-3.5" /> Why the agent drafted this
            </span>
            {action.evidence.map((e) => (
              <p key={e} className="text-xs text-muted-foreground">
                {e}
              </p>
            ))}
          </div>
        )}

        {action.needsApproval && (
          <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            <ShieldCheck className="size-3.5" />
            {action.approverGroup}
            {action.fourEyes && ' · two approvers'}
            {action.approvals.map((a) => (
              <span key={a.by + a.at}>
                · approved by {a.by} {relativeTime(a.at)}
              </span>
            ))}
          </p>
        )}
        {action.result && <p className="text-xs text-emerald-700 dark:text-emerald-400">{action.result}</p>}
        {action.rejectedReason && <p className="text-xs text-red-700 dark:text-red-400">Rejected: {action.rejectedReason}</p>}

        {pending && (
          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            <LoadingButton size="sm" isLoading={busy === 'approve'} disabled={!!busy || iApproved} onClick={() => (action.consequence ? setDialog('confirm') : onApprove())} title={iApproved ? 'You approved this already. A second person must approve it.' : undefined}>
              <Check className="size-4" /> {iApproved ? 'Waiting on second approver' : action.status === 'awaiting_second' ? 'Approve as second' : action.kind === 'reply' ? 'Approve and send' : 'Approve and run'}
            </LoadingButton>
            <Button size="sm" variant="outline" disabled={!!busy} onClick={() => setDialog('edit')}>
              <Pencil className="size-4" /> Edit
            </Button>
            <Button size="sm" variant="outline" disabled={!!busy} onClick={() => setDialog('reject')}>
              <X className="size-4" /> Reject
            </Button>
          </div>
        )}
      </CardContent>

      {action.consequence && (
        <ConfirmActionDialog
          open={dialog === 'confirm'}
          onOpenChange={(o) => !o && setDialog(null)}
          title={`${action.label}?`}
          consequence={action.consequence}
          runsNow={!action.fourEyes || action.approvals.length > 0}
          confirmLabel={!action.fourEyes || action.approvals.length > 0 ? `Approve and ${action.kind === 'reply' ? 'send' : 'run'}` : 'Approve as first'}
          isPending={busy === 'approve'}
          onConfirm={onApprove}
        />
      )}
      <TextDialog
        open={dialog === 'reject'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Reject ${action.label.toLowerCase()}?`}
        description="The action will not run. The agent gets your reason as feedback."
        label="Reason"
        placeholder="e.g. Amount is the whole order; only the duplicate should be refunded"
        initial=""
        confirmLabel="Reject"
        destructive
        isPending={busy === 'reject'}
        onConfirm={onReject}
      />
      <TextDialog
        open={dialog === 'edit'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Edit ${action.label.toLowerCase()}`}
        description={action.approvals.length ? 'Editing clears the approval already given; it has to be approved again.' : 'Approve after saving. The edit is logged on the case.'}
        label={action.kind === 'reply' ? 'Reply' : 'Tool input (JSON)'}
        initial={action.input}
        rows={action.kind === 'reply' ? 10 : 8}
        mono={action.kind === 'tool'}
        confirmLabel="Save"
        isPending={busy === 'edit'}
        onConfirm={onEdit}
      />
    </Card>
  );
}

function TextDialog({
  open,
  onOpenChange,
  title,
  description,
  label,
  placeholder,
  initial,
  rows = 4,
  mono,
  confirmLabel,
  destructive,
  isPending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  label: string;
  placeholder?: string;
  initial: string;
  rows?: number;
  mono?: boolean;
  confirmLabel: string;
  destructive?: boolean;
  isPending: boolean;
  onConfirm: (value: string) => Promise<unknown>;
}) {
  const [value, setValue] = React.useState(initial);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setValue(initial);
      setError(null);
    }
  }, [open, initial]);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={title}
      description={description}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            variant={destructive ? 'destructive' : 'default'}
            isLoading={isPending}
            onClick={async () => {
              if (!value.trim()) return setError(`${label} is required.`);
              try {
                await onConfirm(value);
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            {confirmLabel}
          </LoadingButton>
        </div>
      }
    >
      <FormField id="action-text" label={label} error={error ?? undefined}>
        <Textarea id="action-text" rows={rows} value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} className={mono ? 'font-mono text-xs' : undefined} aria-invalid={!!error} />
      </FormField>
    </DialogShell>
  );
}
