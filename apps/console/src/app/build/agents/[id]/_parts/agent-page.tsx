'use client';

import { RecordActions } from '@/components/shared/record-actions';
import { useWorkspaceIdentity } from '@/hooks/me-queries';
import { ReviewNotice } from '@/components/shared/review-notice';
import { SaveState } from '@/components/shared/save-state';
import * as React from 'react';
import Link from 'next/link';
import { useParams, usePathname, useRouter } from 'next/navigation';
import { ArrowLeft, Bot, CircleAlert, FlaskConical, Info, MoreHorizontal, Pause, Play, RefreshCw, Rocket, Send, Sparkles, Star, Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';

import {
  type AgentDraft,
  changedSections,
  draftOf,
  followLimits,
  GuardrailsSection,
  AgentJobField,
  InstructionsSection,
  KnowledgeSection,
  WidgetsSection,
  LimitsSection,
  RecentRunsCard,
  sameValue,
  ToolsSection,
  UsedInCard,
} from '@/components/agents/agent-settings';
import { AgentBriefEditor, legacyBrief, MoveIntoBrief } from '@/components/agents/agent-brief-editor';
import { ModelSelect } from '@/components/agents/model-select';
import { AgentModelLimitsSection } from '@/components/agents/agent-model-limits-section';
import { AgentCompareView } from '@/components/agents/test-compare';
import { AgentUsesLink } from '@/components/agents/agent-uses-line';
import { AgentVersionsView } from '@/components/agents/agent-versions-view';
import { ViewPromptDialog } from '@/components/agents/view-prompt-dialog';
import { EditableTitle } from '@/components/shared/editable-title';
import { PromptModeDialogs } from '@/components/agents/prompt-mode-dialogs';
import { MemorySection } from '@/components/agents/memory-section';
import { RequestAgentPublishDialog } from '@/components/agents/request-agent-publish-dialog';
import { useSendMessage } from '@/hooks/chat-queries';
import { useAddReference } from '@/hooks/references-queries';
import type { InstructionDocumentHandle } from '@/components/shared/instruction-document';
import { keptEdits, keptEditsByGroup } from '@/lib/kept-edits';
import { LeaveGuard } from '@/components/shared/leave-guard';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import type { AgentBrief, PromptMode } from '@/lib/types/domain';
import type { PublishBlocker } from '@/lib/types/references';
import { AgentTestPanel } from '@/components/agents/agent-test-panel';
import { LivePlacesPanel } from '@/components/channels/hub/live-places';
import { AgentChatChannel, AgentIdSection } from '@/components/agents/agent-channels';
import { SkillMenuSection } from '@/components/agents/skill-menu-section';
import { MakeDefaultAgentDialog } from '@/components/chat/make-default-agent';
import { AgentSkillsSection, type AttachFilter } from '@/components/skills/agent-skills-section';
import { useAgentSkills, useAttachSkill, useDetachSkill } from '@/hooks/skill-queries';
import { TabsList, TabsTrigger } from '@/components/ui/tabs';
import { EvalsTab } from './evals-tab';
import { DraftBriefDialog } from '@/components/agents/draft-brief-dialog';

import { useInstructionsAssist } from './instructions-assist';
import { useAgentAutosave } from './use-agent-autosave';
import { WidgetEmbeds } from '@/components/deployments/widget-embed';
import { PageLayout } from '@/components/page-layout';
import { PageTabPanel, PageTabs } from '@/components/shared/page-tabs';
import { BuilderFieldset, ReadOnlyNotice } from '@/components/shared/builder-only';
import { DangerZone } from '@/components/shared/danger-zone';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { LockedReason } from '@/components/shared/locked-reason';
import { announcePublish } from '@/components/shared/publish-result';
import { AgentAvailabilityBadge, AgentVersionBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import {
  useAgent,
  useAgentPaused,
  useAgentPublishCheck,
  useAgentPublishPreview,
  useAgentRuns,
  useAgentVersions,
  useDeleteAgent,
  useLookups,
  useModelAliases,
  useRequestAgentPublish,
  useReview,
  useRestoreAgent,
  useChangeAgentKnowledge,
  useChangeAgentTools,
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

/** Each tab is its own address under /build/agents/[id]; Compare is a page under Versions. */
const TABS = ['settings', 'evals', 'channels', 'versions', 'usage', 'limits'] as const;
type Tab = (typeof TABS)[number];
const tabOf = (pathname: string): { tab: Tab; compare: boolean } => {
  const [, , , , seg, sub] = pathname.split('/');
  return { tab: (TABS as readonly string[]).includes(seg) ? (seg as Tab) : 'settings', compare: seg === 'versions' && sub === 'compare' };
};

function AgentErrorState({ onRetry, retrying, error }: { onRetry: () => void; retrying: boolean; error: unknown }) {
  return (
    <div className="flex flex-col gap-6 px-6 py-6 lg:px-8">
      <Button variant="ghost" size="sm" className="self-start" asChild>
        <a href="/build/agents">
          <ArrowLeft className="size-4" /> Agents
        </a>
      </Button>
      <QueryError what="this agent" onRetry={onRetry} retrying={retrying} error={error} back={{ label: 'Back to agents', href: '/build/agents' }} />
    </div>
  );
}

/**
 * Agent settings. An agent is configuration that workflows borrow, so the page is one form: every section
 * edits a shared draft and Save records it as a new version. Workflows keep the version they were published with.
 */
/** The workflows that use the agent besides its own one-step workflow, which publishes with it. */
const others = (a: Agent) => a.usedIn.filter((u) => !u.own);

export function AgentPageRoot() {
  const { id } = useParams<{ id: string }>();
  const query = useAgent(id);
  if (query.isPending) return <RecordSkeleton railSide="right" />;
  if (query.isError)
    return <AgentErrorState onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />;
  // Keyed by id only: a save can open a new draft version, and a remount then would drop edits made while it was in flight.
  return <AgentSettingsPage key={query.data.id} agent={query.data} />;
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
  const changeTools = useChangeAgentTools(agent.id);
  const changeKnowledge = useChangeAgentKnowledge(agent.id);
  const setPaused = useAgentPaused(agent.id);
  const restore = useRestoreAgent(agent.id);
  const requestPublish = useRequestAgentPublish(agent.id);
  const me = useWorkspaceIdentity()?.user.email;
  const [publishOpen, setPublishOpen] = React.useState(false);
  const [deployOpen, setDeployOpen] = React.useState(false);
  const widgetScriptUrl = useWidgetScriptUrl();
  // The newest version's state decides the header: a draft offers Request publish, one in review links to it.
  const newest = versions.data?.find((v) => v.version === agent.version);
  const remove = useDeleteAgent();
  const skills = useAgentSkills(agent.id);
  const attachSkill = useAttachSkill(agent.id);
  const detachSkill = useDetachSkill(agent.id);
  const pathname = usePathname();
  const { tab, compare } = tabOf(pathname);
  const setTab = (t: Tab) => router.push(`/build/agents/${agent.id}/${t}`, { scroll: false });

  const saved = React.useMemo(() => draftOf(agent), [agent]);
  const [draft, setDraft] = React.useState<AgentDraft>(saved);
  // A newer copy of the agent (a refetch after a cached first paint, a change made elsewhere, another person's save
  // read again) moves every field the draft has not edited. Left stale, those fields differ from `saved`, and autosave
  // would write the old values back over the newer copy.
  const savedBefore = React.useRef(saved);
  React.useEffect(() => {
    const before = savedBefore.current;
    savedBefore.current = saved;
    // Limits, guardrails and the other grouped settings move setting by setting.
    if (before !== saved) setDraft((d) => keptEditsByGroup(before, d, saved));
  }, [saved]);
  const set =<K extends keyof AgentDraft>(k: K, v: AgentDraft[K]) => setDraft((d) => followLimits({ ...d, [k]: v }, agent.toolIds, agent.collections));
  // The prompt is a brief unless the builder switched to plain text. A legacy agent (no brief) shows its job line as
  // Purpose and its instructions as How to answer, and stays as it is until a brief field is edited.
  const mode: PromptMode = agent.promptMode === 'full' ? 'full' : 'brief';
  const [briefEdit, setBriefEdit] = React.useState<AgentBrief | null>(null);
  const briefSaved = React.useMemo(() => agent.brief ?? legacyBrief(agent), [agent]);
  // The brief is saved whole, so an edited brief is moved onto a newer copy the same way: the fields this person
  // changed keep their text and the rest take the newer copy's. Left whole, the next save would send the other
  // person's fields back as they were before their edit.
  const briefBefore = React.useRef(briefSaved);
  React.useEffect(() => {
    const before = briefBefore.current;
    briefBefore.current = briefSaved;
    if (!sameValue(before, briefSaved)) setBriefEdit((b) => b && keptEdits(before, b, briefSaved));
  }, [briefSaved]);
  const brief = briefEdit ?? briefSaved;
  const [draftOpen, setDraftOpen] = React.useState(false);
  const briefDirty = briefEdit !== null && !sameValue(briefEdit, agent.brief ?? null);
  const purposeMissing = mode === 'brief' && briefDirty && !briefEdit!.purpose.trim();
  const errors = { name: draft.name.trim() ? undefined : 'The agent needs a name.', role: mode === 'full' && !draft.role.trim() ? 'Describe the job in one line.' : undefined };
  const valid = !errors.name && !errors.role && !purposeMissing;
  const sections = changedSections(saved, draft);
  const dirty = sections.length > 0 || briefDirty;
  const [attach, setAttach] = React.useState<AttachFilter | null>(null);
  const [modeAsked, setModeAsked] = React.useState<PromptMode | null>(null);
  const docControls = React.useRef<InstructionDocumentHandle>(null);
  const addReference = useAddReference(agent.id);
  const assist = useInstructionsAssist({
    agent,
    dirty,
    alwaysOn: (skills.data?.pins ?? []).filter((p) => p.loading === 'always'),
    onAttachAlways: () => (setAttach('always'), requestAnimationFrame(() => document.getElementById('agent-skills')?.scrollIntoView({ block: 'center' }))),
  });

  const [deleteOpen, setDeleteOpen] = React.useState(false);
  // Test in the header brings the side panel into view on a narrow screen.
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

  // Pausing only means something once a version is published; before that no run can use the agent.
  const pausable = agent.publishedVersion !== null;
  const teamCanBuild = useCanBuild();
  // The agent's own flags (the detail response asks the routes' checks); the team's permission until they load.
  const canBuild = agent.canEdit ?? teamCanBuild;
  // A version waiting in Reviews is read-only: a change goes in after it is decided.
  const locked = newest?.state === 'in_review';
  const waitingId = locked ? (newest?.reviewId ?? null) : null;
  const waiting = useReview(waitingId);
  const editable = canBuild && !locked;
  const check = useAgentPublishCheck(agent.id, agent.version, canBuild && newest?.state === 'draft');
  const preview = useAgentPublishPreview(agent.id, agent.version, canBuild && newest?.state === 'draft');
  const purposeProblem: PublishBlocker[] = purposeMissing ? [{ kind: 'missing_field', id: null, position: { field: 'brief.purpose', step: null, index: null }, message: 'Job is empty. Say what this agent is for.' }] : [];
  const problems = [...purposeProblem, ...(check.data?.problems ?? [])];
  const goTo = (field: string) => {
    setTab('settings');
    requestAnimationFrame(() => docControls.current?.focus({ field }));
  };
  const insertReference = async (ref: { kind: 'tool' | 'knowledge' | 'skill' | 'agent' | 'workflow'; id: string }) => {
    try {
      const r = await addReference.mutateAsync(ref);
      toast.success(r.added.length ? `Added ${r.added.map((a) => a.label).join(', ')} to ${agent.name}` : `${agent.name} already has it`, { description: `Saved as v${r.agentVersion}.` });
    } catch (e) {
      toast.error('Couldn’t add it to this agent', { description: (e as Error).message });
    }
  };
  const isAdmin = useCanSetDefaultAgent();
  const defaultId = useDefaultAgent().data?.agentId;
  const [makeDefaultOpen, setMakeDefaultOpen] = React.useState(false);
  const liveUse = agent.usedIn.filter((u) => u.status === 'live');
  const { saveNow, saveError, stale, reload, reading } = useAgentAutosave({
    agent,
    update,
    draft,
    saved,
    brief: briefDirty ? briefEdit : null,
    mode,
    ready: editable && dirty && valid,
    onBriefSaved: (sent) => setBriefEdit((b) => (b && sameValue(b, sent) ? null : b)),
  });
  // A grant or a removal is its own save on the stored list, never part of the draft the page autosaves.
  const setTools = (change: { add?: string[]; remove?: string[] }) =>
    changeTools.mutate(change, { onError: (e) => toast.error('Couldn’t change the tools', { description: e.message }) });
  // So is a knowledge base picked or removed, which an @ insert changes too.
  const setKnowledge = (change: { add: string[]; remove: string[] }) =>
    changeKnowledge.mutate(change, { onError: (e) => toast.error('Couldn’t change the knowledge bases', { description: e.message }) });
  // Plain text is never turned on from here (one prompt text); an agent already in it can move into the brief.
  const switchMode = () =>
    // The plain text goes under How to answer whole, so nothing the builder typed is dropped by the move.
    update.mutate({ promptMode: 'brief', brief: { ...(agent.brief ?? legacyBrief(agent)), howToAnswer: agent.instructions }, base: agent }, {
      onSuccess: () => (setModeAsked(null), toast.success('Moved into the brief', { description: 'The next version uses the prompt written from the brief.' })),
      onError: (e) => (setModeAsked(null), toast.error('Couldn’t switch', { description: e.message })),
    });
  const togglePaused = () =>
    setPaused.mutate(!agent.paused, {
      onSuccess: (a) => toast.success(a.paused ? `Paused ${a.name}` : `Resumed ${a.name}`, { description: a.paused ? 'New runs stop using it until you resume it. Its versions and pins are unchanged.' : `New runs use v${a.publishedVersion} again.` }),
      onError: (e) => toast.error(agent.paused ? 'Couldn’t resume the agent' : 'Couldn’t pause the agent', { description: e.message }),
    });


  return (
    <PageTabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
      <PageLayout
        icon={Bot}
        backHref="/build/agents"
        title={editable ? <EditableTitle value={draft.name} onChange={(v) => set('name', v)} label="Agent name" error={errors.name} /> : draft.name}
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
          <>
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
              <TabsTrigger value="versions">Versions</TabsTrigger>
              <TabsTrigger value="usage">Usage</TabsTrigger>
              <TabsTrigger value="limits">Limits</TabsTrigger>
            </TabsList>
          </>
        }
        actions={
          // A draft the person may not publish says why and who can, rather than offering nothing.
          !canBuild ? (
            newest?.state === 'draft' && agent.canPublish === false ? <LockedReason area="agents" action="publish" label="Request publish" /> : undefined
          ) : (
            <RecordActions
              status={<SaveState status={stale ? 'stale' : update.isPending ? 'saving' : saveError ? 'failed' : dirty ? 'unsaved' : 'saved'} detail={stale ?? saveError ?? (dirty && !valid ? 'Fix the highlighted fields to save' : null)} onRetry={saveNow} />}
              save={{ onSave: saveNow, disabled: !dirty || !valid || !editable || !!stale, saving: update.isPending, testId: 'agent-save' }}
              test={
                <Button
                  variant="outline"
                  onClick={() => {
                    setTab('settings');
                    requestAnimationFrame(() => panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
                  }}
                  data-testid="test-agent-button"
                >
                  <FlaskConical className="size-4" /> Test
                </Button>
              }
              primary={
                <>
                  {newest?.state === 'draft' && agent.canPublish !== false && (
                    <Button onClick={() => (purposeMissing ? goTo('brief.purpose') : setPublishOpen(true))} disabled={dirty && !purposeMissing} title={dirty && !purposeMissing ? 'Saving your changes first' : preview.data?.reviewRequired ? 'Goes to a reviewer first' : undefined} data-testid="request-agent-publish">
                      <Rocket className="size-4" /> Publish
                    </Button>
                  )}
                  {newest?.state === 'in_review' && newest.reviewId && (
                    <Button variant="outline" asChild title="Opens the request" data-testid="agent-publish-in-review">
                      <Link href={`/work/tasks?review=${newest.reviewId}`}>In review</Link>
                    </Button>
                  )}
                </>
              }
              menu={
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
                        <Star className="size-4" /> Make default
                      </DropdownMenuItem>
                    )}
                    {assist.menuItem}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem className="flex-col items-start text-destructive-text" disabled={liveUse.length > 0 || agent.canDelete === false} onClick={() => setDeleteOpen(true)}>
                      <span className="flex items-center gap-2">
                        <Trash2 className="size-4" /> Delete agent
                      </span>
                      {liveUse.length > 0 && <span className="pl-6 text-xs text-muted-foreground">Used by a live workflow</span>}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              }
            />
          )
        }
      >
        <PageTabPanel value={tab}>
          {tab === 'evals' && agent.controls.evals ? (
            <EvalsTab agent={agent} />
          ) : compare ? (
            <AgentCompareView agentId={agent.id} agentName={agent.name} newest={agent.version} versions={versions.data ?? []} />
          ) : tab === 'versions' ? (
            <div data-testid="agent-versions">
              <AgentVersionsView
                agentId={agent.id}
                newest={agent.version}
                versions={versions.data}
                isPending={versions.isPending}
                isError={versions.isError}
                onRetry={() => versions.refetch()}
                restoring={restore.isPending}
                onPublish={agent.canPublish !== false && !(dirty && !purposeMissing) ? () => (purposeMissing ? goTo('brief.purpose') : setPublishOpen(true)) : undefined}
                onRestore={async (v) => {
                  try {
                    const a = await restore.mutateAsync(v);
                    // The draft is local state and no longer remounts on a new version, so a restore replaces it here.
                    setDraft(draftOf(a));
                    toast.success(`Restored v${v} as v${a.version}`);
                  } catch (e) {
                    toast.error('Restore failed', { description: (e as Error).message });
                  }
                }}
              />
            </div>
          ) : tab === 'usage' ? (
            <div className="grid gap-4 lg:grid-cols-2" data-testid="agent-usage">
              <UsedInCard agent={agent} />
              <RecentRunsCard runs={runs.data} loading={runs.isPending} />
            </div>
          ) : tab === 'limits' ? (
            <div className="flex max-w-3xl flex-col gap-4" data-testid="agent-limits">
              <BuilderFieldset canEdit={locked ? false : agent.canEdit}>
                <WidgetsSection draft={draft} set={set} toolIds={agent.toolIds} />
              </BuilderFieldset>
              <AgentModelLimitsSection
                model={draft.model}
                patterns={draft.patterns}
                onChange={(v) => (set('model', v.model), set('patterns', v.patterns))}
                disabled={!editable}
              >
                <BuilderFieldset canEdit={locked ? false : agent.canEdit}>
                <MemorySection draft={draft} set={set} />
                <SkillMenuSection draft={draft} set={set} attached={skills.data?.pins.length ?? 0} />
                <GuardrailsSection draft={draft} set={set} shown={agent.controls.guardrails} />
                <LimitsSection draft={draft} set={set} models={modelAliases.data ?? []} tools={tools.data ?? []} toolIds={agent.toolIds} collections={agent.collections} />
                </BuilderFieldset>
              </AgentModelLimitsSection>
            </div>
          ) : tab === 'channels' ? (
            agent.wrapperWorkflowId ? (
              <div className="flex flex-col gap-4">
                {/* Where each version is live, then the embeds' own snippets and keys, which are made here. */}
                <LivePlacesPanel kind="agent" id={agent.id} name={agent.name} between={<AgentChatChannel agent={agent} />} />
                <AgentIdSection agent={agent} />
                <WidgetEmbeds agentId={agent.id} publishedVersion={agent.publishedVersion} scriptUrl={widgetScriptUrl} createOpen={deployOpen} onCreateOpenChange={setDeployOpen} canEdit={agent.canEdit} />
              </div>
            ) : (
              <EmptyState icon={Send} title="Publish the agent to put it in channels" description="Chat, embeds and workflows use a published version. Request publish from the header, then come back here." />
            )
          ) : (
          <SplitView id="agent-settings" bare defaultLeft={62} leftMin="40" rightMin="30" left={
    <div className="flex min-w-0 flex-col gap-4">
              <ReadOnlyNotice noun="agents" canEdit={agent.canEdit} teamId={agent.teamId} teamName={agent.teamName} />
              <LeaveGuard unsaved={dirty && editable} failed={!!saveError} />
              <ReviewNotice
                testId="agent-locked"
                reviewId={waitingId}
                version={agent.version}
                canWithdraw={!!me && waiting.data?.agentPublish?.requestedBy === me}
                onSendAgain={(follows) => requestPublish.mutateAsync({ version: agent.version, note: newest?.note ?? 'Sent again', follows })}
                sendingAgain={requestPublish.isPending}
              />
              {stale && (
                <Alert data-testid="agent-stale-base">
                  <Users />
                  <AlertTitle>Someone else saved this agent</AlertTitle>
                  <AlertDescription>
                    <p>{stale} Your unsaved changes are kept on this page and nothing more is saved until you reload. Reloading shows their version with your changes on top, and saves them.</p>
                    <Button variant="outline" size="sm" onClick={() => void reload()} disabled={reading} data-testid="agent-stale-reload">
                      <RefreshCw className="size-3.5" /> Reload
                    </Button>
                  </AlertDescription>
                </Alert>
              )}
              {saveError && !update.isPending && (
                <Alert data-testid="agent-save-failed">
                  <CircleAlert />
                  <AlertTitle>Your last change didn’t save</AlertTitle>
                  <AlertDescription>
                    <p>It is kept on this page. Check your connection, then retry.</p>
                    <p className="text-xs">{saveError}</p>
                    <Button variant="outline" size="sm" onClick={saveNow} data-testid="agent-save-retry">
                      <RefreshCw className="size-3.5" /> Retry
                    </Button>
                  </AlertDescription>
                </Alert>
              )}
              {/* What opens something to read (the model button, the uses link, Model and limits) stays outside the read-only fieldsets: a disabled fieldset disables every button in it. */}
              <div className="flex flex-wrap items-center gap-2" data-testid="agent-slim-row">
                <fieldset disabled={!editable} className="flex min-w-0 max-w-full items-center gap-2 border-0 p-0" data-testid="agent-model-button">
                  <label htmlFor="ag-model" className="text-sm text-muted-foreground">Model</label>
                  <ModelSelect id="ag-model" value={draft.model} onValueChange={(v) => set('model', v)} aliases={modelAliases.data ?? []} className="w-auto max-w-full" />
                </fieldset>
              </div>
              {/* No read-only fieldset here: the editor takes readOnly, and View prompt in its footer stays usable. */}
              {briefEdit !== null && agent.brief === null && (
                <Alert data-testid="agent-brief-notice">
                  <Info />
                  <AlertTitle>This agent is now written as a brief</AlertTitle>
                  <AlertDescription>
                    <p>The next version uses the prompt written from these headings. Its job line is the Purpose and its instructions are How to answer.</p>
                  </AlertDescription>
                </Alert>
              )}
              <AgentBriefEditor
                agentId={agent.id}
                name={agent.name}
                brief={brief}
                onBrief={setBriefEdit}
                cardHeader={
                  <Button variant="ghost" size="sm" onClick={() => setDraftOpen(true)} title="Propose a brief from a description of the job" data-testid="agent-brief-draft">
                    <Sparkles className="size-3.5" /> Draft
                  </Button>
                }
                mode={mode}
                instructions={draft.instructions}
                onInstructions={(t) => set('instructions', t)}
                readOnly={!editable}
                problems={problems}
                onInsert={insertReference}
                controls={docControls}
                toolbar={assist.toolbar}
                footer={assist.footer}
                textareaRef={assist.textareaRef}
                cardFooter={
                  <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2" data-testid="agent-brief-footer">
                    <AgentUsesLink uses={agent.uses} />
                    <div className="flex items-center gap-1">
                      {editable && mode === 'full' && <MoveIntoBrief onChoose={() => setModeAsked('brief')} disabled={dirty || update.isPending} />}
                      <ViewPromptDialog agentId={agent.id} version={agent.version} name={agent.name} />
                    </div>
                  </div>
                }
              />
              <BuilderFieldset canEdit={locked ? false : agent.canEdit}>
              {mode === 'full' && <AgentJobField draft={draft} set={set} error={errors.role} />}
              </BuilderFieldset>
              <div className="flex flex-col gap-4">
                <BuilderFieldset canEdit={locked ? false : agent.canEdit}>
                  <ToolsSection draft={draft} set={set} toolIds={agent.toolIds} onChange={setTools} stale={agent.staleToolIds} grantable={tools.data ?? []} />
                  <KnowledgeSection collections={agent.collections} onChange={setKnowledge} />
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
                </BuilderFieldset>
              </div>
              <PromptModeDialogs to={modeAsked} onCancel={() => setModeAsked(null)} onConfirm={switchMode} pending={update.isPending} />
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
                held={(tools.data ?? []).filter((t) => agent.toolIds.includes(t.id)).map((t) => ({ name: t.name, approval: t.requiresApproval ? (t.approval ?? 'a review') : null }))}
                threadId={testThreadId}
                onThreadIdChange={setTestThreadId}
                canTest={canBuild}
              />
            </aside>
    } />
          )}

          <RequestAgentPublishDialog
            agentId={agent.id}
            onGoTo={goTo}
            onAddBack={(ref) => void insertReference(ref)}
            adding={addReference.isPending}
            open={publishOpen}
            onOpenChange={setPublishOpen}
            version={agent.version}
            publishedVersion={agent.publishedVersion}
            owner={teamName}
            evalSummary={newest?.evalSummary}
            isPending={requestPublish.isPending}
            onSubmit={async (note) => {
              const r = await requestPublish.mutateAsync({ version: agent.version, note });
              announcePublish({ name: agent.name, version: agent.version, live: r.status === 'approved', liveNote: 'New conversations use it.', decidedBy: `Another publisher in ${teamName}`, reviewId: r.id, openReview: (id) => router.push(`/work/tasks?review=${id}`) });
            }}
          />
          {assist.dialogs}
          <DraftBriefDialog agentId={agent.id} brief={brief} onBrief={setBriefEdit} open={draftOpen} onOpenChange={setDraftOpen} />
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
                router.push('/build/agents');
              } catch (e) {
                toast.error('Couldn’t delete the agent', { description: (e as Error).message });
              }
            }}
          />
        </PageTabPanel>
      </PageLayout>
    </PageTabs>
  );
}
