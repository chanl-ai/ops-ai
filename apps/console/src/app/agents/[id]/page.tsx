'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, Bot, FlaskConical, MoreHorizontal, Pause, Play, Rocket, Send, Star, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import {
  type AgentDraft,
  changedSections,
  draftOf,
  followLimits,
  GuardrailsSection,
  HistoryCard,
  IdentitySection,
  InstructionsSection,
  KnowledgeSection,
  WidgetsSection,
  LimitsSection,
  RecentRunsCard,
  ToolsSection,
  UsedInCard,
} from '@/components/agents/agent-settings';
import { MemorySection } from '@/components/agents/memory-section';
import { RequestAgentPublishDialog } from '@/components/agents/request-agent-publish-dialog';
import { useSendMessage } from '@/hooks/chat-queries';
import { useKnowledgeBases } from '@/hooks/knowledge-queries';
import { AgentTestPanel, TEST_TABS, type TestTab } from '@/components/agents/agent-test-panel';
import { LivePlacesPanel } from '@/components/channels/hub/live-places';
import { AgentChatChannel } from '@/components/agents/agent-channels';
import { MakeDefaultAgentDialog } from '@/components/chat/make-default-agent';
import { AgentSkillsSection, type AttachFilter } from '@/components/skills/agent-skills-section';
import { useAgentSkills, useAttachSkill, useDetachSkill } from '@/hooks/skill-queries';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useTabParam } from '@/hooks/use-tab-param';
import { useWidgetTemplates } from '@/hooks/widget-queries';
import { EvalsTab } from './_parts/evals-tab';
import { useInstructionsAssist } from './_parts/instructions-assist';
import { WidgetEmbeds } from '@/components/deployments/widget-embed';
import { PageLayout } from '@/components/page-layout';
import { BuilderFieldset, ReadOnlyNotice } from '@/components/shared/builder-only';
import { DangerZone } from '@/components/shared/danger-zone';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { VersionHistory } from '@/components/shared/version-history';
import { LockedReason } from '@/components/shared/locked-reason';
import { announcePublish } from '@/components/shared/publish-result';
import { AgentAvailabilityBadge, AgentVersionBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import {
  useAgent,
  useAgentPaused,
  useAgentRuns,
  useAgentVersions,
  useCreateWorkflow,
  useDeleteAgent,
  useLookups,
  useModelAliases,
  useRequestAgentPublish,
  useRestoreAgent,
  useGrantableTools,
  useUpdateAgent,
} from '@/hooks/queries';
import { useCanSetDefaultAgent, useDefaultAgent } from '@/hooks/chat-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useWidgetScriptUrl } from '@/hooks/widget-deployment-queries';
import { relativeTime } from '@/lib/format';
import { useTeam } from '@/hooks/use-team';
import { teamLabel } from '@/components/shared/team-name';
import type { Agent } from '@/lib/types/domain';
import { SplitView } from '@/components/shared/setting/split-view';

const TABS = ['settings', 'evals', 'channels'] as const;
type Tab = (typeof TABS)[number];

function AgentErrorState({ onRetry, retrying, error }: { onRetry: () => void; retrying: boolean; error: unknown }) {
  return (
    <div className="flex flex-col gap-6 px-6 py-6 lg:px-8">
      <Button variant="ghost" size="sm" className="self-start" asChild>
        <a href="/agents">
          <ArrowLeft className="size-4" /> Agents
        </a>
      </Button>
      <QueryError what="this agent" onRetry={onRetry} retrying={retrying} error={error} back={{ label: 'Back to agents', href: '/agents' }} />
    </div>
  );
}

/**
 * Agent settings. An agent is configuration that workflows borrow, so the page is one form: every section
 * edits a shared draft and Save records it as a new version. Workflows keep the version they were published with.
 */
/** The workflows that use the agent besides its own one-step workflow, which publishes with it. */
const others = (a: Agent) => a.usedIn.filter((u) => !u.own);

export default function AgentPage() {
  const { id } = useParams<{ id: string }>();
  const query = useAgent(id);
  if (query.isPending) return <RecordSkeleton railSide="right" />;
  if (query.isError)
    return <AgentErrorState onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />;
  return <AgentSettingsPage key={`${query.data.id}-${query.data.version}`} agent={query.data} />;
}

function AgentSettingsPage({ agent }: { agent: Agent }) {
  const router = useRouter();
  const tools = useGrantableTools();
  const modelAliases = useModelAliases();
  const { data: lookups } = useLookups();
  const { teams } = useTeam();
  const teamName = teamLabel(agent.teamId, teams);
  const versions = useAgentVersions(agent.id);
  const runs = useAgentRuns(agent.id);
  const update = useUpdateAgent(agent.id);
  const setPaused = useAgentPaused(agent.id);
  const restore = useRestoreAgent(agent.id);
  const requestPublish = useRequestAgentPublish(agent.id);
  const [publishOpen, setPublishOpen] = React.useState(false);
  const [deployOpen, setDeployOpen] = React.useState(false);
  const widgetScriptUrl = useWidgetScriptUrl();
  // The newest version's state decides the header: a draft offers Request publish, one in review links to it.
  const newest = versions.data?.find((v) => v.version === agent.version);
  const remove = useDeleteAgent();
  const createWorkflow = useCreateWorkflow();
  const skills = useAgentSkills(agent.id);
  const attachSkill = useAttachSkill(agent.id);
  const detachSkill = useDetachSkill(agent.id);
  const [tab, setTab] = useTabParam(TABS, 'settings');

  const saved = React.useMemo(() => draftOf(agent), [agent]);
  const [draft, setDraft] = React.useState<AgentDraft>(saved);
  const set = <K extends keyof AgentDraft>(k: K, v: AgentDraft[K]) => setDraft((d) => followLimits({ ...d, [k]: v }));
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

  const widgetTemplates = useWidgetTemplates();
  // The one draft saves itself (c-172): a second after the last valid change, with no dialog and no note per save.
  const [saveError, setSaveError] = React.useState<string | null>(null);
  // The draft a save failed on: autosave does not send it again until it changes or Retry is pressed (c-172).
  const [failedDraft, setFailedDraft] = React.useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  // The right panel's tab (c-285); Test in the header opens it and brings it into view on a narrow screen.
  const [testTab, setTestTab] = React.useState<TestTab>(TEST_TABS[0]);
  const [testThreadId, setTestThreadId] = React.useState<string>();
  const chat = useSendMessage();
  // A test reply streams for this page only: leaving the page stops it rather than leaving it running unseen. The
  // effect lives here, not in the panel, which remounts when the layout stacks.
  React.useEffect(() => {
    return () => {
      if (testThreadId) chat.stop(testThreadId);
    };
  }, [testThreadId, chat]);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const kbList = useKnowledgeBases({ page: 1, pageSize: 100 });
  const kbNames = React.useMemo(() => Object.fromEntries((kbList.data?.data ?? []).map((k) => [k.id, k.name])), [kbList.data]);

  // Pausing only means something once a version is published; before that no run can use the agent.
  const pausable = agent.publishedVersion !== null;
  const teamCanBuild = useCanBuild();
  // The agent's own flags (the detail response asks the routes' checks); the team's permission until they load.
  const canBuild = agent.canEdit ?? teamCanBuild;
  const isAdmin = useCanSetDefaultAgent();
  const defaultId = useDefaultAgent().data?.agentId;
  const [makeDefaultOpen, setMakeDefaultOpen] = React.useState(false);
  const liveUse = agent.usedIn.filter((u) => u.status === 'live');
  const patchOf = (d: AgentDraft) => {
    const patch: Record<string, unknown> = Object.fromEntries(Object.entries(d).filter(([k, v]) => JSON.stringify(saved[k as keyof AgentDraft]) !== JSON.stringify(v)));
    // The API pins by id and version; the name and tools a pin carries are what the API returned for display.
    // A new pin carries version 0 until saved; the service then pins the published version.
    if (patch.widgetPins) patch.widgetPins = d.widgetPins.map((p) => ({ widgetId: p.widgetId, version: p.version || undefined }));
    return patch;
  };
  const saveNow = () => {
    const sent = JSON.stringify(draft);
    update.mutate(patchOf(draft), {
      onSuccess: () => (setSaveError(null), setFailedDraft(null)),
      onError: (e) => (setSaveError(e.message), setFailedDraft(sent)),
    });
  };
  React.useEffect(() => {
    if (!canBuild || !dirty || !valid || update.isPending || failedDraft === JSON.stringify(draft)) return;
    const t = setTimeout(() => saveNow(), 1000);
    return () => clearTimeout(t);
    // Saves on a change to the draft or once the last save has settled; patchOf reads `saved`, which moves with them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, saved, valid, canBuild, update.isPending, failedDraft]);
  const togglePaused = () =>
    setPaused.mutate(!agent.paused, {
      onSuccess: (a) => toast.success(a.paused ? `Paused ${a.name}` : `Resumed ${a.name}`, { description: a.paused ? 'New runs stop using it until you resume it. Its versions and pins are unchanged.' : `New runs use v${a.publishedVersion} again.` }),
      onError: (e) => toast.error(agent.paused ? 'Couldn’t resume the agent' : 'Couldn’t pause the agent', { description: e.message }),
    });

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
          {/* The availability badge already says whether it is published; this adds only which version is live. */}
          {agent.publishedVersion !== null && (
            <span className="text-xs text-muted-foreground" data-testid="agent-published-version">
              v{agent.publishedVersion} live
            </span>
          )}
          {newest && newest.state !== 'published' && newest.state !== 'superseded' && (
            <span className="flex items-center gap-1.5 text-xs" data-testid="agent-draft-version">
              <span className="font-medium">v{newest.version}</span>
              <AgentVersionBadge state={newest.state} />
            </span>
          )}
          <span className="text-xs text-muted-foreground">
            {teamName} · used in {agent.usedIn.length} workflow{agent.usedIn.length === 1 ? '' : 's'} · updated {relativeTime(agent.updatedAt)}
          </span>
        </>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            <TabsTrigger value="settings">Settings</TabsTrigger>
            {agent.controls.evals && (
              <TabsTrigger value="evals" data-testid="agent-evals-tab-trigger">
                Evals
              </TabsTrigger>
            )}
            <TabsTrigger value="channels" data-testid="agent-channels-tab-trigger">
              Channels
            </TabsTrigger>
          </TabsList>
        </Tabs>
      }
      actions={
        // A draft the person may not publish says why and who can, rather than offering nothing (c-150).
        !canBuild ? (
          newest?.state === 'draft' && agent.canPublish === false ? <LockedReason area="agents" action="publish" label="Request publish" /> : undefined
        ) : (
        <>
          {agent.wrapperWorkflowId && (
            <Button
              variant="outline"
              onClick={() => {
                setTab('channels');
                setDeployOpen(true);
              }}
              data-testid="embed-agent"
            >
              <Send className="size-4" /> Embed on a page
            </Button>
          )}
          {newest?.state === 'draft' && agent.canPublish !== false && (
            <Button variant="outline" onClick={() => setPublishOpen(true)} disabled={dirty} title={dirty ? 'Saving your changes first' : undefined} data-testid="request-agent-publish">
              <Rocket className="size-4" /> Request publish
            </Button>
          )}
          {newest?.state === 'in_review' && newest.reviewId && (
            <Button variant="outline" asChild data-testid="agent-publish-in-review">
              <Link href={`/reviews?review=${newest.reviewId}`}>In review · {newest.reviewId}</Link>
            </Button>
          )}
          <Button
            variant="outline"
            onClick={() => {
              setTab('settings');
              setTestTab('test');
              requestAnimationFrame(() => panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
            }}
            data-testid="test-agent-button"
          >
            <FlaskConical className="size-4" /> Test
          </Button>
          {canBuild && (
            <>
              <span role="status" data-testid="agent-save-status" className={saveError ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}>
                {update.isPending ? 'Saving…' : saveError ? `Not saved: ${saveError}` : dirty ? (valid ? 'Saving soon…' : 'Fix the highlighted fields to save') : `Draft v${agent.version} saved`}
              </span>
              {saveError && !update.isPending && (
                <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={saveNow} data-testid="agent-save-retry">
                  Retry
                </Button>
              )}
            </>
          )}
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
              {isAdmin && agent.availability === 'published' && agent.id !== defaultId && (
                <DropdownMenuItem onClick={() => setMakeDefaultOpen(true)} data-testid="agent-make-default">
                  <Star className="size-4" /> Make default for chat
                </DropdownMenuItem>
              )}
              {assist.menuItem}
              <DropdownMenuSeparator />
              <DropdownMenuItem className="flex-col items-start text-destructive" disabled={liveUse.length > 0 || agent.canDelete === false} onClick={() => setDeleteOpen(true)}>
                <span className="flex items-center gap-2">
                  <Trash2 className="size-4" /> Delete agent
                </span>
                {liveUse.length > 0 && <span className="pl-6 text-xs text-muted-foreground">Used by a live workflow</span>}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
        )
      }
    >
      {tab === 'evals' && agent.controls.evals ? (
        <EvalsTab agent={agent} />
      ) : tab === 'channels' ? (
        agent.wrapperWorkflowId ? (
          <div className="flex flex-col gap-4">
            {/* Where each version is live (c-242), then the embeds' own snippets and keys, which are made here. */}
            <LivePlacesPanel kind="agent" id={agent.id} name={agent.name} between={<AgentChatChannel agent={agent} />} />
            <WidgetEmbeds agentId={agent.id} publishedVersion={agent.publishedVersion} scriptUrl={widgetScriptUrl} createOpen={deployOpen} onCreateOpenChange={setDeployOpen} canEdit={agent.canEdit} />
          </div>
        ) : (
          <EmptyState icon={Send} title="Publish the agent to put it in channels" description="Chat, embeds and workflows use a published version. Request publish from the header, then come back here." />
        )
      ) : (
      <SplitView id="agent-settings" bare defaultLeft={62} leftMin="40" rightMin="30" left={
<div className="flex min-w-0 flex-col gap-4">
          <ReadOnlyNotice noun="agents" canEdit={agent.canEdit} teamId={agent.teamId} teamName={agent.teamName} />
          <BuilderFieldset canEdit={agent.canEdit}>
          <IdentitySection draft={draft} set={set} teamId={agent.teamId} models={modelAliases.data ?? []} errors={errors} channels={agent.controls.channels} agentId={agent.id} />
          <InstructionsSection draft={draft} set={set} toolbar={assist.toolbar} footer={assist.footer} textareaRef={assist.textareaRef} />
          <ToolsSection draft={draft} set={set} stale={agent.staleToolIds} />
          <KnowledgeSection draft={draft} set={set} />
          <WidgetsSection draft={draft} set={set} />
          <MemorySection draft={draft} set={set} />
          <AgentSkillsSection
            agentName={agent.name}
            data={skills.data}
            isPending={skills.isPending}
            isError={skills.isError}
            onRetry={() => skills.refetch()}
            blockedReason={dirty ? 'Your changes are still saving; skills change once they are saved.' : undefined}
            busy={attachSkill.isPending || detachSkill.isPending}
            attach={attach}
            onAttachChange={setAttach}
            onAttach={async (skillId, version, name, moving) => {
              const after = await attachSkill.mutateAsync({ skillId, version });
              const pinned = after.pins.find((p) => p.skillId === skillId);
              const label = pinned ? `${pinned.name} v${pinned.pinnedVersion}` : name;
              toast.success(moving ? `Moved ${name} to v${version}` : `Attached ${label}`, { description: `Saved ${agent.name} as v${agent.version + 1}. Workflows adopt it on their next publish.` });
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
          <GuardrailsSection draft={draft} set={set} shown={agent.controls.guardrails} />
          <LimitsSection draft={draft} set={set} models={modelAliases.data ?? []} tools={tools.data ?? []} />
          </BuilderFieldset>
          {canBuild && (
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
          )}
        </div>
} right={
<aside ref={panelRef} className="scroll-mt-4" aria-label="Test and agent details">
          <AgentTestPanel
            agentId={agent.id}
            agentName={agent.name}
            kbNames={kbNames}
            held={(tools.data ?? []).filter((t) => draft.toolIds.includes(t.id)).map((t) => ({ name: t.name, approval: t.requiresApproval ? (t.approval ?? 'a review') : null }))}
            tab={testTab}
            onTabChange={setTestTab}
            threadId={testThreadId}
            onThreadIdChange={setTestThreadId}
            versions={<HistoryCard versions={versions.data} loading={versions.isPending} onOpen={() => setHistoryOpen(true)} />}
            newestVersion={agent.version}
            savedVersions={versions.data ?? []}
            usedIn={
              <>
                <UsedInCard agent={agent} onCreateChat={createChat} creating={createWorkflow.isPending} />
                <RecentRunsCard runs={runs.data} loading={runs.isPending} />
              </>
            }
          />
        </aside>
} />
      )}

      <RequestAgentPublishDialog
        agentId={agent.id}
        open={publishOpen}
        onOpenChange={setPublishOpen}
        version={agent.version}
        publishedVersion={agent.publishedVersion}
        owner={teamName}
        evalSummary={newest?.evalSummary}
        isPending={requestPublish.isPending}
        onSubmit={async (note) => {
          const r = await requestPublish.mutateAsync({ version: agent.version, note });
          announcePublish({ name: agent.name, version: agent.version, live: r.status === 'approved', liveNote: 'New conversations use it.', decidedBy: `Another publisher in ${teamName}`, reviewId: r.id, openReview: (id) => router.push(`/reviews?review=${id}`) });
        }}
      />
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
          <SheetHeader className="border-b px-5 py-4 pr-12">
            <SheetTitle>Version history</SheetTitle>
            <SheetDescription>Published versions and the one draft your edits save into. Restoring copies a version into the draft. Workflows pin the published version.</SheetDescription>
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
      <MakeDefaultAgentDialog agent={agent} open={makeDefaultOpen} onOpenChange={setMakeDefaultOpen} />
      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="agent"
        entityName={agent.name}
        requireNameConfirmation
        description={others(agent).length ? `${agent.name} is used in ${others(agent).map((u) => u.workflowName).join(', ')}. Those steps fail until another agent is chosen.` : 'No other workflow uses this agent.'}
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
