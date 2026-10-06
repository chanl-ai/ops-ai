'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { ChevronDown, CircleDashed, FlaskConical, GitCompareArrows, KeyRound, Plus, SearchX, ShieldAlert, ShieldCheck, Trash2, Unplug } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { ActivityPanel } from '@/components/tools/activity-panel';
import { ReasonDialog, RequestApprovalDialog } from '@/components/tools/approval-dialogs';
import { ApprovalsTable } from '@/components/tools/approvals-table';
import { ConnectionChip } from '@/components/integrations/integration-meta';
import { ApprovalStateBadge, ENV_LABEL, ModuleMark, ModuleTypeBadge } from '@/components/tools/module-meta';
import { OperationSheet } from '@/components/tools/operation-sheet';
import { OperationsTable } from '@/components/tools/operations-table';
import { ReviewPanel } from '@/components/tools/review-panel';
import { TestConsole } from '@/components/tools/test-console';
import { ChangeList, VersionsPanel } from '@/components/tools/versions-panel';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useLookups } from '@/hooks/queries';
import {
  useDecideModuleApproval,
  useDeleteModule,
  useDiscardModuleChanges,
  useModuleActivity,
  usePublishModuleVersion,
  useRequestModuleApproval,
  useRequestModuleReview,
  useRevokeModuleApprovals,
  useTestModule,
  useToolModule,
  useUpdateOperation,
} from '@/hooks/tool-module-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { ApiError } from '@/lib/api';
import { plural, shortDate } from '@/lib/format';
import type { ModuleApproval, OperationPatch } from '@/lib/types/tool-modules';

const TABS = ['operations', 'test', 'access', 'approval', 'connection', 'activity', 'versions'] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = { operations: 'Operations', test: 'Test console', access: 'Access', approval: 'Approval', connection: 'Connection', activity: 'Activity', versions: 'Versions' };
const REJECT = ['Scope wider than the workflow needs', 'Missing justification', 'Use a read-only operation instead', 'Workflow not yet approved by its owner'];
const REVOKE = ['No longer needed', 'Workflow retired', 'Security review finding', 'Granted in error'];

export default function ModulePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'operations');
  const query = useToolModule(id);
  const activity = useModuleActivity(id, tab === 'activity');
  const { data: lookups } = useLookups();
  const updateOp = useUpdateOperation();
  const publish = usePublishModuleVersion();
  const discard = useDiscardModuleChanges();
  const review = useRequestModuleReview();
  const request = useRequestModuleApproval();
  const decide = useDecideModuleApproval();
  const revoke = useRevokeModuleApprovals();
  const test = useTestModule();
  const remove = useDeleteModule();
  const [opId, setOpId] = React.useState<string | null>(null);
  const [publishOpen, setPublishOpen] = React.useState(false);
  const [note, setNote] = React.useState('');
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [requestOpen, setRequestOpen] = React.useState(false);
  const [approving, setApproving] = React.useState<ModuleApproval | null>(null);
  const [rejecting, setRejecting] = React.useState<ModuleApproval | null>(null);
  const [revoking, setRevoking] = React.useState<ModuleApproval | null>(null);
  const [deleteOpen, setDeleteOpen] = React.useState(false);

  React.useEffect(() => {
    test.reset();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (query.isPending)
    return (
      <PageLayout title="Module" backHref="/tools">
        <PageSkeleton statCards={0} tableRows={6} showToolbar={false} />
      </PageLayout>
    );
  if (query.isError)
    return (
      <PageLayout title="Module" backHref="/tools">
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Module not found" description="It may have been deleted, or the link is wrong." action={{ label: 'Back to tools', href: '/tools' }} />
        ) : (
          <QueryError what="this module" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </PageLayout>
    );

  const m = query.data;
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });
  const opIndex = m.operations.findIndex((o) => o.id === opId);
  const op = opIndex >= 0 ? m.operations[opIndex] : null;
  const major = m.pendingChanges.some((c) => c.major);
  const reviewOpenNow = m.reviews.some((r) => r.decision === 'pending');
  const requested = m.approvals.filter((a) => a.status === 'requested').length;
  const stageOp = (opIdArg: string, patch: OperationPatch, done: string) =>
    updateOp.mutateAsync({ id: m.id, operationId: opIdArg, patch }).then((x) => {
      const name = x.operations.find((o) => o.id === opIdArg)?.name;
      const breaking = x.pendingChanges.find((c) => c.operation === name && c.major && c.kind === 'removed');
      if (breaking) toast.warning(`${done}: major change`, { description: `${breaking.detail}. Publishing opens a security review.` });
      else toast.success(done, { description: 'Staged. Workflows get it when you publish a version.' });
    }, fail('stage the change'));

  return (
    <PageLayout
      icon={<ModuleMark name={m.displayName} className="size-8" />}
      title={m.displayName}
      badge={<ApprovalStateBadge state={m.approvalState} />}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <ModuleTypeBadge type={m.type} />
          <span className="text-xs">{m.status === 'draft' ? `Draft v${m.version}` : `v${m.version}`}</span>
          <span>Owner {m.ownerTeam}</span>
          <span className="max-w-full truncate font-mono text-xs">{m.endpoint}</span>
          <ConnectionChip connection={m.connection} />
        </span>
      }
      backHref="/tools"
      actions={
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setTab('test')}>
            <FlaskConical className="size-4" /> Test
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button>
                Actions <ChevronDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={m.status === 'draft'} onClick={() => setRequestOpen(true)}>
                <Plus className="size-4" /> Request approval for a workflow
              </DropdownMenuItem>
              <DropdownMenuItem disabled={reviewOpenNow} onClick={() => setReviewOpen(true)}>
                <ShieldCheck className="size-4" /> Request security review
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href="/access">
                  <KeyRound className="size-4" /> All access grants
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="size-4" /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            {TABS.map((t) => (
              <TabsTrigger key={t} value={t}>
                {LABEL[t]}
                {t === 'operations' && <span className="ml-1 text-muted-foreground tabular-nums">{m.operations.length}</span>}
                {t === 'access' && requested > 0 && <span className="ml-1 text-amber-700 tabular-nums dark:text-amber-400">{requested}</span>}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      }
    >
      <div className="flex flex-col gap-4">
        {m.pendingChanges.length > 0 && (
          <Alert>
            <GitCompareArrows className="size-4" />
            <AlertTitle>{plural(m.pendingChanges.length, 'unpublished change')}</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>{major ? 'Includes a major change: publishing opens a security review, and workflows need new approvals before they move to it.' : 'Minor changes: workflows take them at their next publish, which re-runs their tests.'}</p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => (setNote(''), setPublishOpen(true))}>
                  Publish version
                </Button>
                <LoadingButton size="sm" variant="outline" isLoading={discard.isPending} onClick={() => discard.mutate(m.id, { onSuccess: () => toast.success('Changes discarded'), onError: fail('discard the changes') })}>
                  Discard
                </LoadingButton>
              </div>
            </AlertDescription>
          </Alert>
        )}
        {m.status === 'draft' && (
          <Alert>
            <CircleDashed className="size-4" />
            <AlertTitle>Draft: Security has not reviewed it</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>Workflows cannot request it yet. Check the operations’ access classes and record bindings, then request a review.</p>
              <Button size="sm" variant="outline" onClick={() => setReviewOpen(true)}>
                <ShieldCheck className="size-4" /> Request security review
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {m.status === 'in_review' && (
          <Alert>
            <ShieldCheck className="size-4" />
            <AlertTitle>Security is reviewing v{m.version}</AlertTitle>
            <AlertDescription>Workflows can request it now; approvals take effect once the review is approved.</AlertDescription>
          </Alert>
        )}
        {m.drift && (
          <Alert variant="destructive">
            <ShieldAlert className="size-4" />
            <AlertTitle>The server’s tools changed since review</AlertTitle>
            <AlertDescription>The MCP server lists tools that are not in the reviewed snapshot. The gateway refuses them; reviewed operations keep working. Request a re-review to expose the new ones.</AlertDescription>
          </Alert>
        )}
        {!m.reachable && (
          <Alert variant="destructive">
            <Unplug className="size-4" />
            <AlertTitle>Unreachable from the gateway</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>
                {m.connection && m.connection.status !== 'healthy' && m.connection.status !== 'expiring'
                  ? `Its connection ${m.connection.name} is ${m.connection.status === 'revoked' ? 'revoked' : m.connection.status === 'error' ? 'failing to sign in' : 'expired'}. Calls fail into the workflow’s human step until it is fixed in Integrations.`
                  : 'Calls fail into the workflow’s human step until the system responds.'}
              </p>
              {m.connection && (
                <Button size="sm" variant="outline" className="border-destructive/40 text-foreground" asChild>
                  <Link href={`/integrations/${m.connection.id}`}>Open connection</Link>
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}

        {tab === 'operations' && (
          <OperationsTable
            operations={m.operations}
            onOpen={(o) => setOpId(o.id)}
            toggling={updateOp.isPending}
            onToggle={(o, enabled) => stageOp(o.id, { enabled }, enabled ? `Exposed ${o.name}` : `Hid ${o.name}`)}
          />
        )}
        {tab === 'test' && (
          <TestConsole
            operations={m.operations}
            contexts={m.runContexts}
            published={m.status === 'published'}
            onRun={(input) => test.mutate({ id: m.id, ...input })}
            onReset={() => test.reset()}
            running={test.isPending}
            result={test.data}
            error={test.error?.message}
          />
        )}
        {tab === 'access' && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted-foreground">
                Each workflow calls only the operations its approval names, until it expires. Decided by {m.ownerTeam}; never by the person who asked.{' '}
                <Link href="/access" className="font-medium text-foreground underline-offset-4 hover:underline">
                  See every grant
                </Link>
              </p>
              <Button size="sm" variant="outline" disabled={m.status === 'draft'} onClick={() => setRequestOpen(true)}>
                <Plus className="size-4" /> Request approval
              </Button>
            </div>
            {m.approvals.length ? (
              <ApprovalsTable
                approvals={m.approvals}
                operations={m.operations}
                currentUser={lookups?.currentUser.name ?? ''}
                busy={decide.isPending || revoke.isPending}
                onRevoke={setRevoking}
                onDecide={(a, decision) => (decision === 'rejected' ? setRejecting(a) : setApproving(a))}
              />
            ) : (
              <EmptyState icon={KeyRound} title="No workflow is approved" description={m.status === 'draft' ? 'Request a security review first; then workflows can ask for operations.' : 'A workflow asks for the operations it needs, and the owner team approves them with an expiry.'} action={m.status === 'draft' ? undefined : { label: 'Request approval', onClick: () => setRequestOpen(true) }} />
            )}
          </div>
        )}
        {tab === 'approval' && <ReviewPanel major={m.major} reviews={m.reviews} versions={m.versions} drift={m.drift} canRequest={!reviewOpenNow} onRequest={() => setReviewOpen(true)} />}
        {tab === 'connection' &&
          (m.connection ? (
            <div className="flex flex-col gap-3 rounded-lg border bg-card p-4" data-testid="module-connection">
              <ConnectionChip connection={m.connection} className="self-start" />
              <p className="text-sm text-muted-foreground">
                Every operation in this module calls {m.system} through this connection. Its credential, scopes, owner and expiry are managed in Integrations; this module cannot change them.
                {m.auth.header && (
                  <>
                    {' '}
                    The gateway sends it as the <code className="font-mono">{m.auth.header}</code> header.
                  </>
                )}
              </p>
              <Button variant="outline" size="sm" className="self-start" asChild>
                <Link href={`/integrations/${m.connection.id}`}>Open connection</Link>
              </Button>
            </div>
          ) : (
            <EmptyState icon={KeyRound} title="No connection" description="This module is served inside the gateway and needs no credential." />
          ))}
        {tab === 'activity' &&
          (activity.isPending ? (
            <div className="flex flex-col gap-4">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-64 w-full" />
            </div>
          ) : activity.isError ? (
            <QueryError what="activity" onRetry={() => activity.refetch()} retrying={activity.isFetching} error={activity.error} />
          ) : (
            <ActivityPanel module={m} activity={activity.data} />
          ))}
        {tab === 'versions' && <VersionsPanel versions={m.versions} />}
      </div>

      <OperationSheet
        op={op}
        onOpenChange={(o) => !o && setOpId(null)}
        saving={updateOp.isPending}
        onSave={(patch) => (op ? stageOp(op.id, patch, `Staged changes to ${op.name}`) : Promise.resolve())}
        navigation={
          op
            ? {
                currentIndex: opIndex,
                totalCount: m.operations.length,
                onPrev: opIndex > 0 ? () => setOpId(m.operations[opIndex - 1].id) : undefined,
                onNext: opIndex < m.operations.length - 1 ? () => setOpId(m.operations[opIndex + 1].id) : undefined,
              }
            : undefined
        }
      />

      <DialogShell
        open={publishOpen}
        onOpenChange={setPublishOpen}
        size="md"
        title={major ? 'Publish a major version?' : 'Publish a minor version?'}
        description={major ? 'Security reviews it before any workflow can move to it, and each workflow needs a new approval. Workflows keep calling the current version meanwhile.' : 'Workflows take it at their next publish, which re-runs their tests. Approvals carry over.'}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setPublishOpen(false)} disabled={publish.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={publish.isPending}
              disabled={!note.trim()}
              onClick={() =>
                publish.mutate(
                  { id: m.id, note },
                  {
                    onSuccess: (x) => {
                      toast.success(`Published v${x.version}`, { description: major ? 'Security review requested.' : undefined });
                      setPublishOpen(false);
                    },
                    onError: fail('publish the version'),
                  },
                )
              }
            >
              Publish
            </LoadingButton>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <ChangeList changes={m.pendingChanges} />
          <FormField id="pub-note" label="What changed">
            <Textarea id="pub-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Rate limit raised for month-end volume" />
          </FormField>
        </div>
      </DialogShell>

      <DialogShell
        open={reviewOpen}
        onOpenChange={setReviewOpen}
        size="sm"
        title="Request a security review"
        description={`Security reviews major version ${m.major} once. Every minor version in it reuses the decision.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setReviewOpen(false)} disabled={review.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={review.isPending}
              onClick={() =>
                review.mutate(
                  { id: m.id, note },
                  {
                    onSuccess: () => {
                      toast.success('Security review requested');
                      setReviewOpen(false);
                      setNote('');
                    },
                    onError: fail('request the review'),
                  },
                )
              }
            >
              Request review
            </LoadingButton>
          </div>
        }
      >
        <FormField id="rev-note" label="Note for Security" optional>
          <Textarea id="rev-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. New tools on the server: delete_contact is not needed and stays hidden" />
        </FormField>
      </DialogShell>

      <RequestApprovalDialog
        open={requestOpen}
        onOpenChange={setRequestOpen}
        workflows={lookups?.workflows ?? []}
        operations={m.operations}
        major={m.major}
        isPending={request.isPending}
        onSubmit={(input) => request.mutateAsync({ id: m.id, ...input }).then(() => toast.success('Approval requested', { description: `${m.ownerTeam} decides it.` }))}
      />
      <ConfirmActionDialog
        open={!!approving}
        onOpenChange={(o) => !o && setApproving(null)}
        title={`Approve ${approving?.workflowName ?? ''} in ${approving ? ENV_LABEL[approving.environment].toLowerCase() : ''}?`}
        consequence={
          approving
            ? `${approving.workflowName} can call ${approving.operations.join(', ')} in ${ENV_LABEL[approving.environment].toLowerCase()} from now until ${shortDate(approving.expiresAt)}.${approving.operations.some((n) => m.operations.find((o) => o.name === n)?.fourEyes) ? ' Money operations still need a person’s approval on every call.' : ''}`
            : ''
        }
        details={
          approving
            ? [
                { label: 'Workflow', value: approving.workflowName },
                { label: 'Operations', value: approving.operations.join(', ') },
                { label: 'Environment', value: ENV_LABEL[approving.environment] },
                { label: 'Expires', value: shortDate(approving.expiresAt) },
                { label: 'Requested by', value: approving.requestedBy },
              ]
            : undefined
        }
        runsNow
        note="Takes effect as soon as you confirm. You can revoke it from this tab later."
        confirmLabel="Approve"
        isPending={decide.isPending}
        onConfirm={() =>
          decide.mutateAsync({ id: m.id, approvalId: approving!.id, decision: 'approved' }).then(() => {
            toast.success(`Approved ${approving!.workflowName}`, { description: `${plural(approving!.operations.length, 'operation')} until ${shortDate(approving!.expiresAt)}` });
            setApproving(null);
          })
        }
      />
      <ReasonDialog
        open={!!rejecting}
        onOpenChange={(o) => !o && setRejecting(null)}
        title={`Reject ${rejecting?.workflowName ?? ''}?`}
        description="The workflow keeps any other approval it holds. The requester sees the reason."
        reasons={REJECT}
        confirmLabel="Reject"
        destructive
        isPending={decide.isPending}
        onConfirm={(reason) =>
          decide.mutateAsync({ id: m.id, approvalId: rejecting!.id, decision: 'rejected', reason }).then(() => {
            toast.success(`Rejected ${rejecting!.workflowName}`);
            setRejecting(null);
          }, fail('reject the request'))
        }
      />
      <ReasonDialog
        open={!!revoking}
        onOpenChange={(o) => !o && setRevoking(null)}
        title={`Revoke ${revoking?.workflowName ?? ''}?`}
        description={`Calls to ${revoking ? plural(revoking.operations.length, 'operation') : 'these operations'} are refused from now; a run mid-call finishes that call. The workflow falls into its human step.`}
        reasons={REVOKE}
        confirmLabel="Revoke"
        destructive
        isPending={revoke.isPending}
        onConfirm={(reason) =>
          revoke.mutateAsync({ id: m.id, approvalIds: [revoking!.id], reason }).then((r) => {
            if (r.skipped.length) toast.error('Couldn’t revoke', { description: r.skipped[0].reason });
            else toast.success(`Revoked ${revoking!.workflowName}`);
            setRevoking(null);
          }, fail('revoke the approval'))
        }
      />
      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="module"
        entityName={m.displayName}
        requireNameConfirmation
        description={`Its ${plural(m.operations.length, 'operation')} are removed from every agent that holds them.${m.workflows.length ? ` ${plural(m.workflows.length, 'workflow')} still ${m.workflows.length === 1 ? 'holds an approval' : 'hold approvals'}; revoke ${m.workflows.length === 1 ? 'it' : 'them'} first.` : ''}`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(m.id);
            toast.success(`Deleted ${m.displayName}`);
            router.push('/tools');
          } catch (e) {
            toast.error(`Couldn’t delete ${m.displayName}`, { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
