'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, Bot, FlaskConical, MoreHorizontal, Pause, Play, Rocket, SearchX, Send, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import {
  type AgentDraft,
  changedSections,
  draftOf,
  GuardrailsSection,
  HistoryCard,
  IdentitySection,
  InstructionsSection,
  KnowledgeSection,
  ToolsSection,
  UsedInCard,
} from '@/components/agents/agent-settings';
import { CollectionsDialog } from '@/components/agents/collections-dialog';
import { GrantToolsDialog } from '@/components/agents/grant-tools-dialog';
import { RequestAgentPublishDialog } from '@/components/agents/request-agent-publish-dialog';
import { SaveVersionDialog } from '@/components/agents/save-version-dialog';
import { type TestMessage, TestAgentSheet } from '@/components/agents/test-agent-sheet';
import { RunAsBar } from '@/components/run-as/run-as-bar';
import { AgentSkillsSection, type AttachFilter } from '@/components/skills/agent-skills-section';
import { useAgentSkills, useAttachSkill, useDetachSkill } from '@/hooks/skill-queries';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useEvalCaseFromTurn } from '@/hooks/eval-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { EvalsTab } from './_parts/evals-tab';
import { useInstructionsAssist } from './_parts/instructions-assist';
import { DeploymentsTable } from '@/components/deployments/deployments-table';
import { PageLayout } from '@/components/page-layout';
import { DangerZone } from '@/components/shared/danger-zone';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { VersionHistory } from '@/components/shared/version-history';
import { AgentAvailabilityBadge, AgentVersionBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import {
  useAgent,
  useAgentPaused,
  useAgentVersions,
  useCreateWorkflow,
  useDeleteAgent,
  useLookups,
  useModelAliases,
  useRequestAgentPublish,
  useRestoreAgent,
  useTestAgent,
  useGrantableTools,
  useUpdateAgent,
} from '@/hooks/queries';
import { useRunAsPrincipals } from '@/hooks/run-as-queries';
import { ApiError } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import type { Agent } from '@/lib/types/domain';

const ALL_TOOLS = { page: 1, pageSize: 100 };
const TABS = ['settings', 'evals', 'deployments'] as const;
type Tab = (typeof TABS)[number];

function AgentErrorState({ notFound, onRetry, retrying, error }: { notFound: boolean; onRetry: () => void; retrying: boolean; error: unknown }) {
  return (
    <div className="flex flex-col gap-6 px-6 py-6 lg:px-8">
      <Button variant="ghost" size="sm" className="self-start" asChild>
        <a href="/agents">
          <ArrowLeft className="size-4" /> Agents
        </a>
      </Button>
      {notFound ? (
        <EmptyState icon={SearchX} title="Agent not found" description="It may have been deleted, or the link is wrong." action={{ label: 'Back to agents', href: '/agents' }} />
      ) : (
        <QueryError what="this agent" onRetry={onRetry} retrying={retrying} error={error} />
      )}
    </div>
  );
}

/**
 * Agent settings. An agent is configuration that workflows borrow, so the page is one form: every section
 * edits a shared draft and Save records it as a new version. Workflows keep the version they were published with.
 */
export default function AgentPage() {
  const { id } = useParams<{ id: string }>();
  const query = useAgent(id);
  if (query.isPending) return <RecordSkeleton railSide="right" />;
  if (query.isError)
    return <AgentErrorState notFound={query.error instanceof ApiError && query.error.status === 404} onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />;
  return <AgentSettingsPage key={`${query.data.id}-${query.data.version}`} agent={query.data} />;
}

function AgentSettingsPage({ agent }: { agent: Agent }) {
  const router = useRouter();
  const tools = useGrantableTools();
  const modelAliases = useModelAliases();
  const { data: lookups } = useLookups();
  const principals = useRunAsPrincipals();
  const [runAsId, setRunAsId] = React.useState<string | null>(null);
  const versions = useAgentVersions(agent.id);
  const update = useUpdateAgent(agent.id);
  const setPaused = useAgentPaused(agent.id);
  const restore = useRestoreAgent(agent.id);
  const requestPublish = useRequestAgentPublish(agent.id);
  const [publishOpen, setPublishOpen] = React.useState(false);
  const [deployOpen, setDeployOpen] = React.useState(false);
  // The newest version's state decides the header: a draft offers Request publish, one in review links to it.
  const newest = versions.data?.find((v) => v.version === agent.version);
  const remove = useDeleteAgent();
  const createWorkflow = useCreateWorkflow();
  const test = useTestAgent(agent.id);
  const skills = useAgentSkills(agent.id);
  const attachSkill = useAttachSkill(agent.id);
  const detachSkill = useDetachSkill(agent.id);
  const [tab, setTab] = useTabParam(TABS, 'settings');
  const saveTurn = useEvalCaseFromTurn(agent.id);
  const [savedTurns, setSavedTurns] = React.useState<number[]>([]);

  const saved = React.useMemo(() => draftOf(agent), [agent]);
  const [draft, setDraft] = React.useState<AgentDraft>(saved);
  const set = <K extends keyof AgentDraft>(k: K, v: AgentDraft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const sections = changedSections(saved, draft);
  const dirty = sections.length > 0;
  const [attach, setAttach] = React.useState<AttachFilter | null>(null);
  const assist = useInstructionsAssist({
    agent,
    draft,
    setInstructions: (t) => set('instructions', t),
    tools: tools.data ?? [],
    dirty,
    alwaysOn: (skills.data?.pins ?? []).filter((p) => p.loading === 'always'),
    onAttachAlways: () => setAttach('always'),
  });
  const errors = { name: draft.name.trim() ? undefined : 'The agent needs a name.', role: draft.role.trim() ? undefined : 'Describe the job in one line.' };
  const valid = !errors.name && !errors.role;

  const [grantOpen, setGrantOpen] = React.useState(false);
  const [collectionsOpen, setCollectionsOpen] = React.useState(false);
  const [saveOpen, setSaveOpen] = React.useState(false);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [testOpen, setTestOpen] = React.useState(false);
  const [messages, setMessages] = React.useState<TestMessage[]>([]);

  // Pausing only means something once a version is published; before that no run can use the agent.
  const pausable = agent.publishedVersion !== null;
  const liveUse = agent.usedIn.filter((u) => u.status === 'live');
  const discard = () => {
    const before = draft;
    setDraft(saved);
    toast('Discarded unsaved changes', { action: { label: 'Undo', onClick: () => setDraft(before) } });
  };
  const togglePaused = () =>
    setPaused.mutate(!agent.paused, {
      onSuccess: (a) => toast.success(a.paused ? `Paused ${a.name}` : `Resumed ${a.name}`, { description: a.paused ? 'New runs stop using it until you resume it. Its versions and pins are unchanged.' : `New runs use v${a.publishedVersion} again.` }),
      onError: (e) => toast.error(agent.paused ? 'Couldn’t resume the agent' : 'Couldn’t pause the agent', { description: e.message }),
    });

  const sendTest = (text: string) => {
    setMessages((m) => [...m, { role: 'user', text }]);
    test.mutate({ message: text, runAsId: runAsId ?? undefined }, {
      onSuccess: (turn) => setMessages((m) => [...m, { role: 'agent', text: turn.reply, turn }]),
      onError: (e) => setMessages((m) => [...m, { role: 'error', text: e.message }]),
    });
  };

  /** Saves one test-panel reply as an eval case: the message before it, who it ran as, and what it called and cited. */
  const saveAsTest = (index: number) => {
    const reply = messages[index];
    const question = messages.slice(0, index).reverse().find((m) => m.role === 'user');
    if (!reply?.turn || !question) return;
    saveTurn.mutate(
      { message: question.text, turn: reply.turn, runAsId: reply.turn.permissions?.runAsId },
      {
        onSuccess: (c) => {
          setSavedTurns((s) => [...s, index]);
          toast.success(`Saved “${c.name}” as an eval case`, { description: 'It runs on the next save or when you run evals.', action: { label: 'Open evals', onClick: () => (setTestOpen(false), setTab('evals')) } });
        },
        onError: (e) => toast.error('Couldn’t save the case', { description: e.message }),
      },
    );
  };

  const createChat = () =>
    createWorkflow.mutate(
      { name: `${agent.name} chat`, trigger: 'Chat message', template: 'chat', agentSlug: agent.slug },
      {
        onSuccess: (wf) => {
          toast.success(`Created ${wf.name}`, { description: 'Publish it, then add a deployment.' });
          router.push(`/workflows/${wf.id}`);
        },
        onError: (e) => toast.error('Couldn’t create the workflow', { description: e.message }),
      },
    );

  return (
    <PageLayout
      icon={Bot}
      backHref="/agents"
      title={agent.name}
      description={agent.role}
      badge={
        <>
          <AgentAvailabilityBadge availability={agent.availability} />
          <span className="text-xs text-muted-foreground" data-testid="agent-published-version">
            {agent.publishedVersion === null ? 'Not published' : `Published v${agent.publishedVersion}`}
          </span>
          {newest && newest.state !== 'published' && newest.state !== 'superseded' && (
            <span className="flex items-center gap-1.5 text-xs" data-testid="agent-draft-version">
              <span className="font-medium">v{newest.version}</span>
              <AgentVersionBadge state={newest.state} />
            </span>
          )}
          <span className="text-xs text-muted-foreground">
            {agent.owner} · used in {agent.usedIn.length} workflow{agent.usedIn.length === 1 ? '' : 's'} · updated {relativeTime(agent.updatedAt)}
          </span>
        </>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            <TabsTrigger value="settings">Settings</TabsTrigger>
            <TabsTrigger value="evals" data-testid="agent-evals-tab-trigger">
              Evals
            </TabsTrigger>
            <TabsTrigger value="deployments" data-testid="agent-deployments-tab-trigger">
              Deployments
            </TabsTrigger>
          </TabsList>
        </Tabs>
      }
      actions={
        <>
          {agent.wrapperWorkflowId && (
            <Button
              variant="outline"
              onClick={() => {
                setTab('deployments');
                setDeployOpen(true);
              }}
              data-testid="deploy-agent"
            >
              <Send className="size-4" /> Deploy agent
            </Button>
          )}
          {newest?.state === 'draft' && (
            <Button variant="outline" onClick={() => setPublishOpen(true)} disabled={dirty} title={dirty ? 'Save or discard your changes first' : undefined} data-testid="request-agent-publish">
              <Rocket className="size-4" /> Request publish
            </Button>
          )}
          {newest?.state === 'in_review' && newest.reviewId && (
            <Button variant="outline" asChild data-testid="agent-publish-in-review">
              <Link href={`/reviews?review=${newest.reviewId}`}>In review · {newest.reviewId}</Link>
            </Button>
          )}
          <Button variant="outline" onClick={() => setTestOpen(true)} data-testid="test-agent-button">
            <FlaskConical className="size-4" /> Test
          </Button>
          <Button onClick={() => setSaveOpen(true)} disabled={!dirty || !valid} data-testid="save-agent-button">
            Save as v{agent.version + 1}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" aria-label="More actions">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {pausable && (
                <DropdownMenuItem onClick={togglePaused}>
                  {agent.paused ? <Play className="size-4" /> : <Pause className="size-4" />} {agent.paused ? 'Resume agent' : 'Pause agent'}
                </DropdownMenuItem>
              )}
              {assist.menuItem}
              <DropdownMenuSeparator />
              <DropdownMenuItem className="flex-col items-start text-destructive" disabled={liveUse.length > 0} onClick={() => setDeleteOpen(true)}>
                <span className="flex items-center gap-2">
                  <Trash2 className="size-4" /> Delete agent
                </span>
                {liveUse.length > 0 && <span className="pl-6 text-xs text-muted-foreground">Used by a live workflow</span>}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      }
    >
      {tab === 'evals' ? (
        <EvalsTab agent={agent} />
      ) : tab === 'deployments' ? (
        agent.wrapperWorkflowId ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              {agent.name} deploys through{' '}
              <Link href={`/workflows/${agent.wrapperWorkflowId}`} className="font-medium text-foreground underline underline-offset-2" data-testid="agent-wrapper-link">
                its one-step workflow
              </Link>
              , which publishes whenever the agent does. Console chat is one of these deployments.
            </p>
            <DeploymentsTable workflowId={agent.wrapperWorkflowId} createOpen={deployOpen} onCreateOpenChange={setDeployOpen} />
          </div>
        ) : (
          <EmptyState icon={Send} title="Publish the agent to deploy it" description="An agent deploys once a version is published. Request publish from the header, then come back here." />
        )
      ) : (
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-4">
          <IdentitySection draft={draft} set={set} lookups={lookups} models={modelAliases.data ?? []} errors={errors} />
          <InstructionsSection draft={draft} set={set} toolbar={assist.toolbar} footer={assist.footer} textareaRef={assist.textareaRef} />
          <ToolsSection draft={draft} set={set} tools={tools.data ?? []} onGrant={() => setGrantOpen(true)} />
          <KnowledgeSection draft={draft} onChoose={() => setCollectionsOpen(true)} />
          <AgentSkillsSection
            agentName={agent.name}
            data={skills.data}
            isPending={skills.isPending}
            isError={skills.isError}
            onRetry={() => skills.refetch()}
            blockedReason={dirty ? 'Save or discard your unsaved changes first; changing skills saves a new version.' : undefined}
            busy={attachSkill.isPending || detachSkill.isPending}
            attach={attach}
            onAttachChange={setAttach}
            onAttach={async (skillId, version, name, moving) => {
              await attachSkill.mutateAsync({ skillId, version });
              toast.success(moving ? `Moved ${name} to v${version}` : `Attached ${name} v${version}`, { description: `Saved ${agent.name} as v${agent.version + 1}. Workflows adopt it on their next publish.` });
            }}
            onDetach={async (pin) => {
              try {
                await detachSkill.mutateAsync(pin.skillId);
                toast.success(`Detached ${pin.name}`, { description: `Saved ${agent.name} as v${agent.version + 1}.` });
              } catch (e) {
                toast.error('Couldn’t detach the skill', { description: (e as Error).message });
              }
            }}
          />
          <GuardrailsSection draft={draft} set={set} />
          {dirty && (
            <div data-unsaved-bar className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-3 rounded-lg border border-primary/30 bg-background/95 px-4 py-3 shadow-[0_-6px_16px_-10px_rgb(0_0_0/0.25)] backdrop-blur" role="status" data-testid="unsaved-bar">
              <span className="text-sm">
                Unsaved changes to <span className="font-medium">{sections.join(', ')}</span>
              </span>
              <div className="ml-auto flex gap-2">
                <Button variant="ghost" size="sm" onClick={discard}>
                  Discard
                </Button>
                <Button size="sm" onClick={() => setSaveOpen(true)} disabled={!valid}>
                  Save as v{agent.version + 1}
                </Button>
              </div>
            </div>
          )}
          <DangerZone
            items={[
              ...(pausable
                ? [
                    {
                      title: agent.paused ? 'Resume this agent' : 'Pause this agent',
                      description: agent.paused ? `New runs use v${agent.publishedVersion} again.` : 'New runs stop using it until you resume it. Runs already started finish. Versions, pins and open publish requests are unchanged.',
                      action: agent.paused ? 'Resume' : 'Pause',
                      onClick: togglePaused,
                      disabled: setPaused.isPending,
                    },
                  ]
                : []),
              {
                title: 'Delete this agent',
                description: liveUse.length ? `Used by ${liveUse.map((u) => u.workflowName).join(', ')}, which is live. Remove it from the workflow first.` : 'Nothing live uses it.',
                action: 'Delete',
                destructive: true,
                disabled: liveUse.length > 0,
                onClick: () => setDeleteOpen(true),
              },
            ]}
          />
        </div>
        <aside className="flex flex-col gap-4">
          <UsedInCard agent={agent} onCreateChat={createChat} creating={createWorkflow.isPending} />
          <HistoryCard versions={versions.data} loading={versions.isPending} onOpen={() => setHistoryOpen(true)} />
        </aside>
      </div>
      )}

      <SaveVersionDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        nextVersion={agent.version + 1}
        sections={sections}
        pinnedWorkflows={agent.usedIn.map((u) => u.workflowName)}
        isPending={update.isPending}
        onSave={async (note) => {
          const patch = Object.fromEntries(Object.entries(draft).filter(([k, v]) => JSON.stringify(saved[k as keyof AgentDraft]) !== JSON.stringify(v)));
          const a = await update.mutateAsync({ ...patch, note: note || undefined });
          toast.success(`Saved v${a.version}`, {
            description: `Evals are running on v${a.version}.${a.usedIn.length ? ' Republish the workflows that use it to adopt it.' : ''}`,
            action: tab === 'evals' ? undefined : { label: 'View evals', onClick: () => setTab('evals') },
          });
        }}
      />
      <GrantToolsDialog
        open={grantOpen}
        onOpenChange={setGrantOpen}
        tools={tools.data ?? []}
        loading={tools.isPending}
        granted={draft.toolIds}
        isPending={false}
        onSubmit={async (toolIds) => set('toolIds', toolIds)}
      />
      <CollectionsDialog
        open={collectionsOpen}
        onOpenChange={setCollectionsOpen}
        collections={lookups?.collections ?? []}
        selected={draft.collections}
        isPending={false}
        onSubmit={async (collections) => set('collections', collections)}
      />
      <RequestAgentPublishDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        version={agent.version}
        publishedVersion={agent.publishedVersion}
        owner={agent.owner}
        evalSummary={newest?.evalSummary}
        isPending={requestPublish.isPending}
        onSubmit={async (note) => {
          const r = await requestPublish.mutateAsync({ version: agent.version, note });
          toast.success(`Sent v${agent.version} for publish`, { description: `${r.id} is in Reviews. Another publisher in ${agent.owner} approves it.`, action: { label: 'Open review', onClick: () => router.push(`/reviews?review=${r.id}`) } });
        }}
      />
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
          <SheetHeader className="border-b px-5 py-4 pr-12">
            <SheetTitle>Version history</SheetTitle>
            <SheetDescription>Every save is a draft until a publish review approves it. Restoring saves a new draft. Workflows pin the published version.</SheetDescription>
          </SheetHeader>
          <div className="flex-1 overflow-y-auto px-5 py-4">
            <VersionHistory
              noun="agent"
              currentLabel="Current"
              restoreConsequence="Workflows keep the version they were published with until they are republished."
              versions={versions.data}
              isPending={versions.isPending}
              isError={versions.isError}
              onRetry={() => versions.refetch()}
              restoring={restore.isPending}
              onRestore={async (v) => {
                try {
                  const a = await restore.mutateAsync(v);
                  toast.success(`Restored v${v} as v${a.version}`);
                  setHistoryOpen(false);
                } catch (e) {
                  toast.error('Restore failed', { description: (e as Error).message });
                }
              }}
            />
          </div>
        </SheetContent>
      </Sheet>
      {assist.dialogs}
      <TestAgentSheet
        open={testOpen}
        onOpenChange={setTestOpen}
        agentName={agent.name}
        messages={messages}
        onSend={sendTest}
        isPending={test.isPending}
        onSaveTurn={saveAsTest}
        savingTurn={saveTurn.isPending}
        savedTurns={savedTurns}
        runAs={<RunAsBar principals={principals.data ?? []} loading={principals.isPending} value={runAsId} onChange={setRunAsId} className="shadow-none" />}
      />
      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="agent"
        entityName={agent.name}
        requireNameConfirmation
        description={agent.usedIn.length ? `${agent.name} is used in ${agent.usedIn.map((u) => u.workflowName).join(', ')}. Those steps fail until another agent is chosen.` : 'Nothing uses this agent.'}
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(agent.id);
            toast.success(`Deleted ${agent.name}`);
            router.push('/agents');
          } catch (e) {
            toast.error('Couldn’t delete the agent', { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
