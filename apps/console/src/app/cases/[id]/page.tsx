'use client';

import * as React from 'react';
import { Inbox, ListChecks, Mail, SearchX, Tags, UserPlus, Users, XCircle } from 'lucide-react';
import { useParams } from 'next/navigation';
import { toast } from 'sonner';

import { CaseActionCard } from '@/components/cases/case-action-card';
import { caseIsOpen } from '@/components/cases/case-columns';
import { CaseActivity, CaseConversation } from '@/components/cases/case-thread';
import { PageLayout } from '@/components/page-layout';
import { BulkFieldDialog } from '@/components/shared/bulk';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { CaseStatusBadge, ConfidenceBar, PriorityBadge, SlaText } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAssignCases, useCase, useCaseQueues, useCloseCases, useDecideAction, useEditAction, useSetCaseField } from '@/hooks/case-queries';
import { useLookups } from '@/hooks/queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { useSticky } from '@/hooks/use-sticky';
import { ApiError } from '@/lib/api';
import { dateTime, relativeTime, fieldValue } from '@/lib/format';
import type { CaseField } from '@/lib/types/cases';

const TABS = ['actions', 'conversation', 'activity'] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = { actions: 'Actions', conversation: 'Email', activity: 'Activity' };
const CLOSE_REASONS = ['Resolved', 'Duplicate of another case', 'Not a request for us', 'Spam or phishing'];

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useTabParam(TABS, 'actions');
  const query = useCase(id);
  const { data: lookups } = useLookups();
  const { data: queues } = useCaseQueues();
  const decide = useDecideAction(id);
  const edit = useEditAction(id);
  const setField = useSetCaseField(id);
  const assign = useAssignCases();
  const close = useCloseCases();
  const [busy, setBusy] = React.useState<{ actionId: string; kind: 'approve' | 'reject' | 'edit' } | null>(null);
  const [dialog, setDialog] = React.useState<'assign' | 'close' | null>(null);
  const [editingField, setEditingField] = React.useState<CaseField | null>(null);
  const me = lookups?.currentUser.name;

  if (query.isPending) return <RecordSkeleton />;
  if (query.isError)
    return (
      <PageLayout title="Case" backHref="/cases">
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Case not found" description="It may have been merged, or the link is wrong." action={{ label: 'Back to cases', href: '/cases' }} />
        ) : (
          <QueryError what="this case" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </PageLayout>
    );

  const c = query.data;
  const open = caseIsOpen(c);
  const pendingCount = c.pendingApprovals;
  const run = async (actionId: string, kind: 'approve' | 'reject' | 'edit', fn: () => Promise<unknown>, done: (r: unknown) => void) => {
    setBusy({ actionId, kind });
    try {
      done(await fn());
    } finally {
      setBusy(null);
    }
  };

  return (
    <PageLayout
      icon={Mail}
      title={c.subject}
      badge={<CaseStatusBadge status={c.status} />}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-mono text-xs">{c.id}</span>
          <span>
            {c.requester} · {c.requesterEmail}
          </span>
          <span title={dateTime(c.receivedAt)}>Received {relativeTime(c.receivedAt)}</span>
        </span>
      }
      backHref="/cases"
      actions={
        open && (
          <div className="flex flex-wrap gap-2">
            {c.assignee !== me && me && (
              <LoadingButton
                variant="outline"
                isLoading={assign.isPending && dialog === null}
                onClick={() => assign.mutate({ ids: [c.id], assignee: me }, { onSuccess: () => toast.success(`${c.id} is yours`), onError: (e) => toast.error('Couldn’t assign the case', { description: e.message }) })}
              >
                <UserPlus className="size-4" /> Assign to me
              </LoadingButton>
            )}
            <Button variant="outline" onClick={() => setDialog('assign')}>
              <Users className="size-4" /> Reassign
            </Button>
            <Button variant="outline" onClick={() => setDialog('close')} disabled={pendingCount > 0} title={pendingCount ? 'Decide or reject the waiting actions first' : undefined}>
              <XCircle className="size-4" /> Close case
            </Button>
          </div>
        )
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            {TABS.map((t) => (
              <TabsTrigger key={t} value={t}>
                {LABEL[t]}
                {t === 'actions' && pendingCount > 0 && <span className="ml-1 rounded-full bg-amber-500/15 px-1.5 text-[10px] text-amber-700 tabular-nums dark:text-amber-400">{pendingCount} waiting</span>}
                {t === 'conversation' && <span className="ml-1 text-muted-foreground tabular-nums">{c.messages.length}</span>}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      }
    >
      <RecordLayout
        rail={
          <>
            <AttributeCard title="Case" icon={Inbox} testId="case-rail">
              <FieldRow label="Intent" value={c.intentName} />
              <FieldRow label="Confidence" value={<ConfidenceBar value={c.confidence} />} />
              <FieldRow label="Queue" value={c.queue} />
              <FieldRow label="Priority" value={<PriorityBadge priority={c.priority} />} />
              <FieldRow label="SLA" value={open ? <SlaText minutes={c.slaMinutes ?? 0} open paused={c.status === 'waiting_customer'} /> : 'Closed'} />
              <FieldRow label="Assignee" value={c.assignee} emptyHint="Unassigned" />
              <FieldRow label="Account" value={c.account} mono />
              <FieldRow label="Mailbox" value={c.mailbox} />
              <FieldRow label="Workflow" value={c.workflowName} href={`/workflows/${c.workflowId}?tab=intents`} />
            </AttributeCard>
            <AttributeCard title="Extracted from the email" icon={Tags} testId="case-fields">
              {c.fields.length === 0 && <p className="text-sm text-muted-foreground">This intent extracts no fields.</p>}
              {c.fields.map((f) => (
                <FieldRow
                  key={f.key}
                  label={f.label}
                  value={fieldValue(f.value)}
                  emptyHint="Not found"
                  adornment={f.edited ? <span className="text-[10px] text-muted-foreground">edited</span> : undefined}
                  onEdit={open ? () => setEditingField(f) : undefined}
                />
              ))}
            </AttributeCard>
          </>
        }
      >
        {tab === 'actions' &&
          (c.actions.length === 0 ? (
            <EmptyState icon={ListChecks} title="No actions drafted" description="The agent drafted nothing for this intent. Reply from your mail client or close the case." />
          ) : (
            <div className="flex flex-col gap-3">
              {c.actions.map((a) => (
                <CaseActionCard
                  key={a.id}
                  action={a}
                  currentUser={me}
                  caseOpen={open}
                  busy={busy?.actionId === a.id ? busy.kind : null}
                  onApprove={() =>
                    run(a.id, 'approve', () => decide.mutateAsync({ actionId: a.id, decision: 'approve' }), (r) => {
                      const updated = r as typeof a;
                      if (updated.status === 'awaiting_second') toast(`${a.label} needs a second approver`, { description: `Your approval is recorded. Someone else in ${a.approverGroup} must also approve.` });
                      else toast.success(`${a.label}: ${updated.result ?? 'done'}`);
                    }).catch((e) => toast.error(`Couldn’t approve ${a.label.toLowerCase()}`, { description: (e as Error).message }))
                  }
                  onReject={(reason) => run(a.id, 'reject', () => decide.mutateAsync({ actionId: a.id, decision: 'reject', reason }), () => toast.success(`Rejected ${a.label.toLowerCase()}`, { description: 'The agent has your reason.' }))}
                  onEdit={(input) => run(a.id, 'edit', () => edit.mutateAsync({ actionId: a.id, input }), () => toast.success(`Saved ${a.label.toLowerCase()}`, { description: 'Approve it to run.' }))}
                />
              ))}
            </div>
          ))}
        {tab === 'conversation' && <CaseConversation messages={c.messages} />}
        {tab === 'activity' && <CaseActivity events={c.events} />}
      </RecordLayout>

      <BulkFieldDialog
        open={dialog === 'assign'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Reassign ${c.id}`}
        description="The new assignee sees it in Assigned to me. The SLA clock keeps running."
        fieldLabel="Assignee"
        options={(queues?.assignees ?? []).filter((a) => a !== c.assignee)}
        names={[`${c.id} · ${c.subject}`]}
        confirmLabel="Reassign"
        isPending={assign.isPending}
        onConfirm={async (assignee) => {
          await assign.mutateAsync({ ids: [c.id], assignee });
          toast.success(`Reassigned to ${assignee}`);
        }}
      />
      <BulkFieldDialog
        open={dialog === 'close'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Close ${c.id}`}
        description="No email is sent. If the customer writes again, a new case opens."
        fieldLabel="Reason"
        options={CLOSE_REASONS}
        names={[`${c.id} · ${c.subject}`]}
        confirmLabel="Close case"
        isPending={close.isPending}
        onConfirm={async (reason) => {
          const res = await close.mutateAsync({ ids: [c.id], reason });
          if (res.skipped.length) throw new Error(res.skipped[0].reason);
          toast.success(`Closed ${c.id}`);
        }}
      />
      <EditFieldDialog
        field={editingField}
        onOpenChange={(o) => !o && setEditingField(null)}
        isPending={setField.isPending}
        onSave={async (value) => {
          await setField.mutateAsync({ key: editingField!.key, value });
          toast.success(`${editingField!.label} updated`, { description: 'The change is logged on the case. Drafted actions keep their input until you edit them.' });
        }}
      />
    </PageLayout>
  );
}

function EditFieldDialog({ field, onOpenChange, onSave, isPending }: { field: CaseField | null; onOpenChange: (o: boolean) => void; onSave: (v: string) => Promise<unknown>; isPending: boolean }) {
  const shown = useSticky(field);
  const [value, setValue] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (field) {
      setValue(field.value ?? '');
      setError(null);
    }
  }, [field]);
  return (
    <DialogShell
      open={!!field}
      onOpenChange={onOpenChange}
      size="sm"
      title={`Correct ${shown?.label.toLowerCase() ?? 'field'}`}
      description="Corrections are logged and fed back to the agent's evaluation set."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            onClick={async () => {
              if (!value.trim()) return setError('Enter a value.');
              try {
                await onSave(value.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Save
          </LoadingButton>
        </div>
      }
    >
      <FormField id="case-field" label={shown?.label ?? 'Value'} error={error ?? undefined}>
        <Input id="case-field" value={value} onChange={(e) => setValue(e.target.value)} aria-invalid={!!error} />
      </FormField>
    </DialogShell>
  );
}
