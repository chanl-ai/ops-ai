'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, MoreHorizontal, Pause, Play, Rocket, SearchX, Trash2 } from 'lucide-react';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { toast } from 'sonner';

import { DangerZone } from '@/components/shared/danger-zone';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { VersionHistory } from '@/components/shared/version-history';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { EmailConfigTab } from '@/components/email/email-config-tab';
import { WorkflowEditor } from '@/components/workflows/workflow-editor';
import { WorkflowRuns } from '@/components/workflows/workflow-runs';
import { TestCases } from '@/components/workflows/test-cases';
import { DeploymentsTable } from '@/components/deployments/deployments-table';
import { WorkflowSettingsForm } from '@/components/workflows/workflow-settings';
import {
  useAgents,
  useDeleteWorkflow,
  useLookups,
  useRequestPublish,
  useSaveDraft,
  useValidateWorkflow,
  useRestoreWorkflow,
  useTools,
  useUpdateWorkflow,
  useWorkflow,
  useWorkflowStatus,
  useWorkflowVersions,
} from '@/hooks/queries';
import { useCaseQueues, useTestSampleMail } from '@/hooks/case-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { ApiError } from '@/lib/api';
import { plural } from '@/lib/format';
import type { EmailWorkflowConfig, SampleMailInput } from '@/lib/types/cases';

const TABS = ['canvas', 'intents', 'routing', 'approvals', 'runs', 'tests', 'deployments', 'versions', 'settings'] as const;
type Tab = (typeof TABS)[number];
/** Email intake workflows are configured with these forms; other workflows do not show them. */
const EMAIL_TABS: Tab[] = ['intents', 'routing', 'approvals'];
const LABEL: Record<Tab, string> = { canvas: 'Canvas', intents: 'Intents', routing: 'Routing & SLAs', approvals: 'Approval rules', runs: 'Runs', tests: 'Tests', deployments: 'Deployments', versions: 'Versions', settings: 'Settings' };
const ALL_TOOLS = { page: 1, pageSize: 100 };

function EditorSkeleton() {
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="editor-skeleton">
      <div className="flex items-center gap-3 border-b px-6 py-2.5">
        <Skeleton className="size-8" />
        <Skeleton className="h-5 w-56" />
        <Skeleton className="h-8 w-72" />
        <Skeleton className="ml-auto h-8 w-40" />
      </div>
      <div className="flex flex-1">
        <Skeleton className="m-3 hidden w-[236px] rounded-lg md:block" />
        <div className="flex flex-1 items-center justify-center gap-6 p-10">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-44 rounded-xl" />
          ))}
        </div>
        <Skeleton className="m-3 hidden w-72 rounded-lg lg:block" />
      </div>
    </div>
  );
}

export default function WorkflowDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'canvas');
  const query = useWorkflow(id);
  const { data: lookups } = useLookups();
  const tools = useTools(ALL_TOOLS);
  const agentList = useAgents(ALL_TOOLS);
  const versions = useWorkflowVersions(id);
  const validate = useValidateWorkflow(id);
  const requestPublish = useRequestPublish(id);
  const saveDraft = useSaveDraft(id);
  const [deployOpen, setDeployOpen] = React.useState(false);
  const update = useUpdateWorkflow(id);
  const status = useWorkflowStatus(id);
  const restore = useRestoreWorkflow(id);
  const remove = useDeleteWorkflow();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const caseQueues = useCaseQueues();
  const testSample = useTestSampleMail();

  if (query.isPending)
    return tab === 'canvas' ? (
      <EditorSkeleton />
    ) : (
      <div className="flex flex-col">
        <div className="flex items-center gap-3 border-b px-6 py-2.5">
          <Skeleton className="size-8" />
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-8 w-72" />
        </div>
        <div className="px-6 py-5">
          <PageSkeleton statCards={0} tableRows={6} />
        </div>
      </div>
    );
  if (query.isError) {
    return (
      <div className="flex flex-col gap-6 px-6 py-6">
        <Button variant="ghost" size="sm" className="self-start" asChild>
          <Link href="/workflows">
            <ArrowLeft className="size-4" /> Workflows
          </Link>
        </Button>
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Workflow not found" description="It may have been deleted, or the link is wrong." action={{ label: 'Back to workflows', href: '/workflows' }} />
        ) : (
          <QueryError what="this workflow" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </div>
    );
  }

  const wf = query.data;
  const live = wf.status === 'live';
  const isEmail = wf.kind === 'email_intake';
  const visibleTabs = TABS.filter((t) => isEmail || !EMAIL_TABS.includes(t));
  const moneyTools = (tools.data?.data ?? []).filter((t) => t.access === 'money_movement').map((t) => t.name);
  const emailProps = {
    queues: caseQueues.data?.queues ?? [],
    approverGroups: caseQueues.data?.approverGroups ?? [],
    actionOptions: [...(tools.data?.data ?? []).filter((t) => t.enabled).map((t) => t.name), 'send_reply'],
    moneyTools,
    onTestSample: (config: EmailWorkflowConfig, input: SampleMailInput) => testSample.mutateAsync({ config, input }),
    testing: testSample.isPending,
  };
  const toggleStatus = () =>
    status.mutate(live ? 'paused' : 'live', {
      onSuccess: (w) => toast.success(w.status === 'paused' ? `Paused ${w.name}` : `Resumed ${w.name}`, { description: w.status === 'paused' ? 'New triggers are queued, not run. Open reviews stay open.' : 'Queued triggers will run now.' }),
      onError: (e) => toast.error('Couldn’t change the status', { description: e.message }),
    });

  return (
    <>
      <WorkflowEditor
        key={`${wf.id}-${wf.version}`}
        workflow={wf}
        reviewerGroups={lookups?.reviewerGroups ?? []}
        slaOptions={lookups?.slaOptions ?? []}
        moneyTools={moneyTools}
        agents={agentList.data?.data ?? []}
        toolOptions={(tools.data?.data ?? []).filter((t) => t.enabled)}
        lookupOptions={{ collections: lookups?.collections ?? [], owners: lookups?.owners ?? [], workflows: lookups?.workflows ?? [] }}
        onValidate={(graph) => validate.mutateAsync({ graph })}
        onRequestPublish={(graph, note, validationRunId, checksFailing) => requestPublish.mutateAsync({ graph, note, validationRunId, checksFailing })}
        isRequesting={requestPublish.isPending}
        onSaveDraft={(graph) => saveDraft.mutateAsync(graph)}
        showCanvas={tab === 'canvas'}
        tabs={
          <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
            <TabsList>
              {visibleTabs.map((t) => (
                <TabsTrigger key={t} value={t}>
                  {LABEL[t]}
                  {t === 'runs' && wf.openReviews > 0 && <span className="ml-1 rounded-full bg-amber-500/15 px-1.5 text-[10px] text-amber-700 tabular-nums dark:text-amber-400">{wf.openReviews} paused</span>}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
        extraActions={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" className="size-8" aria-label="More actions">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {wf.status !== 'draft' && (
                <DropdownMenuItem onClick={toggleStatus}>
                  {live ? <Pause className="size-4" /> : <Play className="size-4" />} {live ? 'Pause workflow' : 'Resume workflow'}
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="size-4" /> Delete workflow
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        }
      >
        {isEmail && (tab === 'intents' || tab === 'routing' || tab === 'approvals') && <EmailConfigTab tab={tab} {...emailProps} />}
        {!isEmail && EMAIL_TABS.includes(tab) && <EmptyState icon={SearchX} title="Not an email workflow" description="Intents, routing and approval rules apply to email intake workflows." />}
        {tab === 'runs' && <WorkflowRuns workflowId={wf.id} />}
        {tab === 'tests' && isEmail && (
          <div className="mb-6">
            <EmailConfigTab tab="sample" {...emailProps} />
          </div>
        )}
        {tab === 'tests' && <TestCases workflowId={wf.id} liveGraph={wf.graph} tools={(tools.data?.data ?? []).map((t) => t.name)} />}
        {tab === 'deployments' &&
          (wf.status === 'draft' ? (
            <EmptyState icon={Rocket} title="Not published yet" description="Deployments serve a published version. Request a publish from the canvas first." />
          ) : (
            <DeploymentsTable workflowId={wf.id} createOpen={deployOpen} onCreateOpenChange={setDeployOpen} />
          ))}
        {tab === 'versions' && (
          <div className="max-w-3xl">
            <VersionHistory
              noun="workflow"
              versions={versions.data}
              isPending={versions.isPending}
              isError={versions.isError}
              onRetry={() => versions.refetch()}
              restoring={restore.isPending}
              onRestore={async (v) => {
                try {
                  const w = await restore.mutateAsync(v);
                  toast.success(`Restored v${v} as v${w.version}`);
                } catch (e) {
                  toast.error('Restore failed', { description: (e as Error).message });
                }
              }}
            />
          </div>
        )}
        {tab === 'settings' && (
          <div className="flex max-w-3xl flex-col gap-6">
            <WorkflowSettingsForm
              workflow={wf}
              owners={lookups?.owners ?? []}
              isSaving={update.isPending}
              onSave={async (input) => {
                try {
                  await update.mutateAsync(input);
                  toast.success('Settings saved');
                } catch (e) {
                  toast.error('Couldn’t save settings', { description: (e as Error).message });
                }
              }}
            />
            <DangerZone
              items={[
                ...(wf.status !== 'draft'
                  ? [
                      {
                        title: live ? 'Pause this workflow' : 'Resume this workflow',
                        description: live ? 'New triggers queue instead of running. Open reviews stay open.' : 'Queued triggers run immediately.',
                        action: live ? 'Pause' : 'Resume',
                        onClick: toggleStatus,
                        disabled: status.isPending,
                      },
                    ]
                  : []),
                { title: 'Delete this workflow', description: 'Removes the workflow and its history. Blocked while reviews are open.', action: 'Delete', destructive: true, onClick: () => setDeleteOpen(true) },
              ]}
            />
          </div>
        )}
      </WorkflowEditor>

      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="workflow"
        entityName={wf.name}
        requireNameConfirmation
        description={wf.openReviews ? `${plural(wf.openReviews, 'review is', 'reviews are')} still open. Decide them or pause the workflow first.` : 'Runs history and versions are deleted with it.'}
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(wf.id);
            toast.success(`Deleted ${wf.name}`);
            router.push('/workflows');
          } catch (e) {
            toast.error('Couldn’t delete the workflow', { description: (e as Error).message });
          }
        }}
      />
    </>
  );
}
