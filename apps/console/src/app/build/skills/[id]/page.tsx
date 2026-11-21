'use client';

import { RecordActions } from '@/components/shared/record-actions';
import { SaveState } from '@/components/shared/save-state';
import { ReviewNotice } from '@/components/shared/review-notice';
import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Activity, Archive, TriangleAlert, BookOpen, Copy, Download, FlaskConical, History, Inbox, MoreHorizontal, Paperclip, Send, Sparkles, Trash2, Users, Wrench } from 'lucide-react';
import { toast } from 'sonner';

import { openLink } from '@/components/files/file-actions';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { FieldRow } from '@/components/shared/field-row';
import { SKILL_LOADING_LABEL } from '@/components/skills/skill-loading';
import { QueryError } from '@/components/shared/query-states';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { DeprecateSkillDialog, RequestReviewDialog } from '@/components/skills/skill-dialogs';
import { EditClassBadge, ORIGIN, SkillStatusBadge, ToolChips } from '@/components/skills/skill-meta';
import { SkillUsedBySheet } from '@/components/skills/skill-used-by-sheet';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { BuilderFieldset, ReadOnlyNotice } from '@/components/shared/builder-only';
import { announcePublish } from '@/components/shared/publish-result';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useDownloadFile } from '@/hooks/file-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useDeleteSkill, useDeprecateSkill, useDuplicateSkill, useExportSkills, useRequestSkillReview, useSkill } from '@/hooks/skill-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { plural, relativeTime } from '@/lib/format';
import type { Carried } from '@/lib/kept-edits';
import type { SkillDetail } from '@/lib/types/skills';

import { ActivityTab } from './_parts/activity-tab';
import { ResourcesTab } from './_parts/resources-tab';
import { type KeptText, type Form as SkillForm, SkillEditor, type SkillSaveState } from './_parts/skill-editor';
import { TestsTab } from './_parts/tests-tab';
import { VersionsTab } from './_parts/versions-tab';

// What `?tab=` opens over the page, so links to a skill's tests, versions, files and agents keep landing there.
// `instructions` is the page itself; the rest are side sheets.
const PANELS = ['instructions', 'resources', 'tests', 'used_by', 'versions', 'activity'] as const;
const SHEETS = {
  tests: { title: 'Tests', description: 'Cases the newest version must pass before it can be published.', width: 'sm:max-w-4xl' },
  versions: { title: 'Versions', description: 'Every saved version, newest first.', width: 'sm:max-w-3xl' },
  activity: { title: 'Activity', description: 'How often agents load the skill, and recent turns that did.', width: 'sm:max-w-4xl' },
  resources: { title: 'Files and templates', description: 'Reference files and text templates the skill can read.', width: 'sm:max-w-2xl' },
} as const;

export default function SkillPage() {
  const { id } = useParams<{ id: string }>();
  const query = useSkill(id);
  if (query.isPending) return <RecordSkeleton />;
  if (query.isError)
    return (
      <PageLayout icon={Sparkles} title="Skill" backHref="/build/skills">
        <QueryError what="this skill" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} back={{ label: 'Back to skills', href: '/build/skills' }} />
      </PageLayout>
    );
  return <SkillView skill={query.data} />;
}

function SkillView({ skill: s }: { skill: SkillDetail }) {
  const router = useRouter();
  const [panel, setPanel] = useTabParam(PANELS, 'instructions');
  const sheet = panel in SHEETS ? SHEETS[panel as keyof typeof SHEETS] : null;
  const close = (open: boolean) => !open && setPanel('instructions');
  // Adding a file or restoring a version saves a draft, and the form is drawn again from it: unsaved text would go.
  const [unsaved, setUnsaved] = React.useState(false);
  // The editor owns the autosave; the header shows its state and a Save that sends the waiting change now.
  const saveCtl = React.useRef<SkillSaveState | null>(null);
  const [saveView, setSaveView] = React.useState<Pick<SkillSaveState, 'status' | 'detail' | 'canSave'> | null>(null);
  const onSaveState = React.useCallback((st: SkillSaveState) => {
    saveCtl.current = st;
    setSaveView((v) => (v && v.status === st.status && v.detail === st.detail && v.canSave === st.canSave ? v : { status: st.status, detail: st.detail, canSave: st.canSave }));
  }, []);
  // The editor is drawn again for each saved version; after a save someone else made first, it hands its unsaved text
  // here so the form drawn on their version starts with it.
  const carried = React.useRef<Carried<SkillForm> | null>(null);
  // The person's own text after that reload, kept read-only beside theirs.
  const keptText = React.useRef<KeptText | null>(null);
  const waits = unsaved && (panel === 'resources' || panel === 'versions');
  const request = useRequestSkillReview(s.id);
  const deprecate = useDeprecateSkill(s.id);
  const duplicate = useDuplicateSkill();
  const remove = useDeleteSkill();
  const exportSkills = useExportSkills();
  const download = useDownloadFile();
  // The service checks skills: edit on every save, publish request and pin (routers/skills.py).
  const canBuild = useCanBuild('skills');
  const [dialog, setDialog] = React.useState<'review' | 'deprecate' | 'delete' | null>(null);
  const newest = s.versions[0];
  const live = s.usage.filter((u) => u.agentAvailability === 'published');
  const reviewReason = s.publishCheck.canRequest ? undefined : s.publishCheck.blockers.map((b) => b.message).join(' ');

  const runExport = async (version?: number) => {
    try {
      const f = await exportSkills.mutateAsync({ ids: [s.id], version });
      toast.success(`Exported ${f.name}`, { description: 'Stored in Files.', action: { label: 'Download', onClick: async () => openLink(await download.mutateAsync(f.id), f.name) } });
    } catch (e) {
      toast.error('Couldn’t export', { description: (e as Error).message });
    }
  };

  return (
    <>
      <PageLayout
        icon={Sparkles}
        backHref="/build/skills"
        title={s.name}
        description={s.loading === 'always' ? 'Always on: added to every turn of every agent that pins it, after the agent’s own instructions' : s.useWhen}
        badge={
          <>
            <SkillStatusBadge status={s.status} />
            <span className="text-xs text-muted-foreground">
              {s.publishedVersion ? `v${s.publishedVersion} published` : 'Not published'}
              {s.draftVersion && s.draftVersion !== s.publishedVersion ? ` · draft v${s.draftVersion}` : ''} · {s.ownerTeam} ·{' '}
              <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setPanel('used_by')} data-testid="skill-used-by-link">
                Used by {plural(s.usedBy, 'agent')}
              </Button>
            </span>
          </>
        }
        actions={
          <RecordActions
            status={canBuild && saveView ? <SaveState status={saveView.status} detail={saveView.detail} onRetry={() => saveCtl.current?.retry()} /> : undefined}
            save={canBuild && saveView ? { onSave: () => void saveCtl.current?.saveNow(), disabled: !saveView.canSave, saving: saveView.status === 'saving', testId: 'save-skill-draft' } : undefined}
            test={
              <Button variant="outline" onClick={() => setPanel('tests')} title={`${plural(s.tests.length, 'test')}`} data-testid="skill-open-tests">
                <FlaskConical className="size-4" /> Test
              </Button>
            }
            primary={
              canBuild && (
                <DisabledReason reason={reviewReason}>
                  <Button onClick={() => setDialog('review')} disabled={!s.publishCheck.canRequest} title="Goes to a reviewer first" data-testid="request-review-button">
                    <Send className="size-4" /> Publish
                  </Button>
                </DisabledReason>
              )
            }
            menu={
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="More actions" data-testid="skill-more">
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setPanel('versions')} data-testid="skill-open-versions">
                  <History className="size-4" /> Versions · {s.versions.length}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setPanel('activity')} data-testid="skill-open-activity">
                  <Activity className="size-4" /> Activity
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setPanel('used_by')} data-testid="skill-open-used-by">
                  <Users className="size-4" /> Used by {plural(s.usedBy, 'agent')}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setPanel('resources')} data-testid="skill-open-resources">
                  <Paperclip className="size-4" /> Files and templates · {newest.content.resources.length}
                </DropdownMenuItem>
                {canBuild && (
                <>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => void runExport()}>
                  <Download className="size-4" /> Export SKILL.md
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() =>
                    duplicate.mutate(s.id, {
                      onSuccess: (d) => {
                        toast.success(`Created ${d.name}`, { description: 'A draft copy with the same tests.' });
                        router.push(`/build/skills/${d.id}`);
                      },
                      onError: (e) => toast.error('Couldn’t duplicate', { description: e.message }),
                    })
                  }
                >
                  <Copy className="size-4" /> Duplicate
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={s.status === 'deprecated' || !s.publishedVersion} onClick={() => setDialog('deprecate')}>
                  <Archive className="size-4" /> Deprecate
                </DropdownMenuItem>
                <DropdownMenuItem className="flex-col items-start text-destructive-text" disabled={live.length > 0} onClick={() => setDialog('delete')}>
                  <span className="flex items-center gap-2">
                    <Trash2 className="size-4" /> Delete skill
                  </span>
                  {live.length > 0 && <span className="pl-6 text-xs text-muted-foreground">Pinned by a live agent</span>}
                </DropdownMenuItem>
                </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            }
          />
        }
      >
          <div className="flex flex-col gap-4">
            <ReadOnlyNotice noun="skills" area="skills" />
            <ReviewNotice
              testId="skill-pending-review"
              reviewId={s.pendingReview?.id ?? null}
              version={s.pendingReview?.version ?? newest.version}
              detail={s.pendingReview ? `${s.pendingReview.approvals} of ${plural(s.pendingReview.needed, 'approval')}` : undefined}
              canWithdraw={canBuild}
              onSendAgain={() => request.mutateAsync(newest.note ?? 'Sent again')}
              sendingAgain={request.isPending}
            />
            {s.status === 'deprecated' && (
              <Alert>
                <Archive />
                <AlertTitle>Deprecated</AlertTitle>
                <AlertDescription>No agent can attach it. {s.usage.length ? `${plural(s.usage.length, 'agent')} still pin a version; detach or replace it there.` : ''}</AlertDescription>
              </Alert>
            )}
            {s.usedBy > 0 && s.status !== 'deprecated' && (
              <Alert data-testid="skill-shared-banner">
                <Users />
                <AlertTitle>Used by {plural(s.usedBy, 'agent')}</AlertTitle>
                <AlertDescription>
                  <span>
                    {s.usedBy === 1 ? 'It keeps the version it uses until it is moved to a newer one.' : 'They keep the version they use until each one is moved to a newer one.'}{' '}
                    <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setPanel('used_by')}>
                      See {s.usedBy === 1 ? 'the agent' : 'the agents'}
                    </Button>
                  </span>
                </AlertDescription>
              </Alert>
            )}
            <BuilderFieldset area="skills">
            <RecordLayout
              rail={
                <>
                  <AttributeCard title="Attributes" icon={Sparkles}>
                    <FieldRow label="Owner team" value={s.ownerTeam} />
                    <FieldRow label="Loading" value={SKILL_LOADING_LABEL[s.loading]} />
                    <FieldRow label="Identifier" value={s.slug} mono />
                    <FieldRow label="Published" value={s.publishedVersion ? `v${s.publishedVersion}` : undefined} />
                    <FieldRow label="Newest" value={`v${newest.version} · ${newest.state.replace('_', ' ')}`} />
                    <FieldRow label="When loaded" value={`${s.tokens.toLocaleString('en-CA')} tokens`} />
                    <FieldRow label="Origin" value={`${ORIGIN[s.origin].label} · ${s.provenance.detail}`} />
                    <FieldRow label="Updated" value={`${relativeTime(s.updatedAt)} by ${s.updatedBy}`} />
                    <div className="flex items-center justify-between gap-2 pt-2 text-sm">
                      <span className="text-muted-foreground">Next publish</span>
                      <EditClassBadge editClass={s.publishCheck.editClass} />
                    </div>
                  </AttributeCard>
                  <AttributeCard title="Tools and knowledge" icon={Wrench} testId="skill-scope-card">
                    <div className="flex flex-col gap-3 text-sm">
                      <div>
                        <div className="mb-1 text-xs text-muted-foreground">{s.content.parts?.length ? 'Tools' : 'Tools · read from the text when saved'}</div>
                        <ToolChips tools={s.content.tools} max={8} />
                      </div>
                      <div>
                        <div className="mb-1 text-xs text-muted-foreground">Knowledge bases</div>
                        {s.content.knowledgeBases.length ? (
                          <div className="flex flex-wrap gap-1">
                            {s.content.knowledgeBases.map((k) => (
                              <Badge key={k} variant="secondary" className="font-normal">
                                {k}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">None</span>
                        )}
                      </div>
                      <div>
                        <div className="mb-1 text-xs text-muted-foreground">Files and templates</div>
                        <span>{newest.content.resources.length ? newest.content.resources.map((r) => r.name).join(', ') : 'None'}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">A skill never grants these. An agent must hold every tool and knowledge base before the skill can be attached.</p>
                    </div>
                  </AttributeCard>
                  {s.provenance.citations.length > 0 && (
                    <AttributeCard title="Sources" icon={BookOpen}>
                      <ul className="flex flex-col gap-1.5 text-xs">
                        {s.provenance.citations.map((c) => (
                          <li key={c.id}>
                            {c.href ? (
                              <Link href={c.href} className="font-medium underline-offset-2 hover:underline">
                                {c.label}
                              </Link>
                            ) : (
                              <span className="font-medium">{c.label}</span>
                            )}
                            {c.detail && <span className="text-muted-foreground"> · {c.detail}</span>}
                          </li>
                        ))}
                      </ul>
                    </AttributeCard>
                  )}
                </>
              }
            >
              <SkillEditor key={`${newest.version}-${newest.savedAt}`} skill={s} canEdit={canBuild} onDirtyChange={setUnsaved} onSaveState={onSaveState} carried={carried} keptText={keptText} />
            </RecordLayout>
            </BuilderFieldset>
          </div>

          <SkillUsedBySheet skill={s} open={panel === 'used_by'} onOpenChange={close} canEdit={canBuild} />
          <DetailSheet
            open={!!sheet}
            onOpenChange={close}
            title={sheet?.title ?? ''}
            description={sheet?.description}
            widthClass={sheet?.width}
            testId="skill-panel-sheet"
            footerActions={
              <Button variant="outline" size="sm" onClick={() => close(false)}>
                Close
              </Button>
            }
          >
            {/* A sheet is drawn outside the page's fieldset, so it gets its own. */}
            <BuilderFieldset area="skills">
              <div className="flex flex-col gap-4">
                {waits && (
                  <Alert data-testid="skill-sheet-unsaved">
                    <TriangleAlert />
                    <AlertTitle>Save your changes first</AlertTitle>
                    <AlertDescription>The skill has changes that are not saved. A change here saves a draft and would drop them, so these controls wait until you save or discard.</AlertDescription>
                  </Alert>
                )}
                <fieldset disabled={waits} className="contents">
                  {panel === 'tests' && <TestsTab skill={s} />}
                  {panel === 'versions' && <VersionsTab skill={s} onExport={runExport} />}
                  {panel === 'activity' && <ActivityTab skill={s} />}
                  {panel === 'resources' && <ResourcesTab skill={s} />}
                </fieldset>
              </div>
            </BuilderFieldset>
          </DetailSheet>

          <RequestReviewDialog
            onJump={() => setDialog(null)}
            open={dialog === 'review'}
            onOpenChange={(o) => !o && setDialog(null)}
            skill={s}
            isPending={request.isPending}
            onSubmit={async (note) => {
              const d = await request.mutateAsync(note);
              announcePublish({ name: s.name, version: newest.version, live: !d.pendingReview, liveNote: 'Agents can attach it now.', decidedBy: `${plural(d.pendingReview?.needed ?? 1, 'approver')} from ${s.ownerTeam}`, reviewId: d.pendingReview?.id, openReview: (id) => router.push(`/work/tasks?review=${id}`) });
            }}
          />
          <DeprecateSkillDialog
            open={dialog === 'deprecate'}
            onOpenChange={(o) => !o && setDialog(null)}
            names={[s.name]}
            pinnedBy={s.usage.length}
            isPending={deprecate.isPending}
            onSubmit={async (reason) => {
              await deprecate.mutateAsync(reason);
              toast.success(`Deprecated ${s.name}`, { description: 'Recorded in the audit log.' });
            }}
          />
          <DeleteDialog
            open={dialog === 'delete'}
            onOpenChange={(o) => !o && setDialog(null)}
            entityType="skill"
            entityName={s.name}
            requireNameConfirmation={s.usage.length > 0}
            description={s.usage.length ? `${s.usage.map((u) => u.agentName).join(', ')} pin${s.usage.length === 1 ? 's' : ''} a version. Deleting detaches it from ${s.usage.length === 1 ? 'that agent' : 'those agents'}.` : 'No agent uses it. Its versions and tests are deleted.'}
            isLoading={remove.isPending}
            onConfirm={async () => {
              try {
                await remove.mutateAsync(s.id);
                toast.success(`Deleted ${s.name}`);
                router.push('/build/skills');
              } catch (e) {
                toast.error('Couldn’t delete the skill', { description: (e as Error).message });
              }
            }}
          />
      </PageLayout>
    </>
  );
}
