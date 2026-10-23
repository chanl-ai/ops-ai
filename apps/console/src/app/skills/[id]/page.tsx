'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Archive, BookOpen, Copy, Download, Inbox, MoreHorizontal, Send, Sparkles, Trash2, Wrench } from 'lucide-react';
import { toast } from 'sonner';

import { openLink } from '@/components/files/file-actions';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { FieldRow } from '@/components/shared/field-row';
import { SKILL_LOADING_LABEL } from '@/components/skills/skill-loading';
import { QueryError } from '@/components/shared/query-states';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { DeprecateSkillDialog, RequestReviewDialog } from '@/components/skills/skill-dialogs';
import { EditClassBadge, ORIGIN, SkillStatusBadge, ToolChips } from '@/components/skills/skill-meta';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { BuilderFieldset, ReadOnlyNotice } from '@/components/shared/builder-only';
import { announcePublish } from '@/components/shared/publish-result';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useDownloadFile } from '@/hooks/file-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useDeleteSkill, useDeprecateSkill, useDuplicateSkill, useExportSkills, useRequestSkillReview, useSkill } from '@/hooks/skill-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { plural, relativeTime } from '@/lib/format';
import type { SkillDetail } from '@/lib/types/skills';

import { ActivityTab } from './_parts/activity-tab';
import { InstructionsTab } from './_parts/instructions-tab';
import { ResourcesTab } from './_parts/resources-tab';
import { TestsTab } from './_parts/tests-tab';
import { UsedByTab } from './_parts/used-by-tab';
import { VersionsTab } from './_parts/versions-tab';

const TABS = ['instructions', 'resources', 'tests', 'used_by', 'versions', 'activity'] as const;
type Tab = (typeof TABS)[number];

export default function SkillPage() {
  const { id } = useParams<{ id: string }>();
  const query = useSkill(id);
  if (query.isPending) return <RecordSkeleton />;
  if (query.isError)
    return (
      <PageLayout icon={Sparkles} title="Skill" backHref="/skills">
        <QueryError what="this skill" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} back={{ label: 'Back to skills', href: '/skills' }} />
      </PageLayout>
    );
  return <SkillView skill={query.data} />;
}

function SkillView({ skill: s }: { skill: SkillDetail }) {
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'instructions');
  const request = useRequestSkillReview(s.id);
  const deprecate = useDeprecateSkill(s.id);
  const duplicate = useDuplicateSkill();
  const remove = useDeleteSkill();
  const exportSkills = useExportSkills();
  const download = useDownloadFile();
  const canBuild = useCanBuild();
  const [dialog, setDialog] = React.useState<'review' | 'deprecate' | 'delete' | null>(null);
  const newest = s.versions[0];
  const live = s.usage.filter((u) => u.agentAvailability === 'published');
  const reviewReason = s.publishCheck.canRequest ? undefined : s.publishCheck.blockers.join(' ');

  const runExport = async (version?: number) => {
    try {
      const f = await exportSkills.mutateAsync({ ids: [s.id], version });
      toast.success(`Exported ${f.name}`, { description: 'Stored in Files.', action: { label: 'Download', onClick: async () => openLink(await download.mutateAsync(f.id), f.name) } });
    } catch (e) {
      toast.error('Couldn’t export', { description: (e as Error).message });
    }
  };

  return (
    <PageLayout
      icon={Sparkles}
      backHref="/skills"
      title={s.name}
      description={s.loading === 'always' ? 'Always on: added to every turn of every agent that pins it, after the agent’s own instructions' : s.useWhen}
      badge={
        <>
          <SkillStatusBadge status={s.status} />
          <span className="text-xs text-muted-foreground">
            {s.publishedVersion ? `v${s.publishedVersion} published` : 'Not published'}
            {s.draftVersion && s.draftVersion !== s.publishedVersion ? ` · draft v${s.draftVersion}` : ''} · {s.ownerTeam} · used by {plural(s.usedBy, 'agent')}
          </span>
        </>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            <TabsTrigger value="instructions">Instructions</TabsTrigger>
            <TabsTrigger value="resources">Resources · {newest.content.resources.length}</TabsTrigger>
            <TabsTrigger value="tests" data-testid="skill-tab-tests">
              Tests · {s.tests.length}
            </TabsTrigger>
            <TabsTrigger value="used_by" data-testid="skill-tab-used-by">
              Used by · {s.usage.length}
            </TabsTrigger>
            <TabsTrigger value="versions" data-testid="skill-tab-versions">
              Versions · {s.versions.length}
            </TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
          </TabsList>
        </Tabs>
      }
      actions={
        canBuild && (
        <>
          <DisabledReason reason={reviewReason}>
            <Button onClick={() => setDialog('review')} disabled={!s.publishCheck.canRequest} data-testid="request-review-button">
              <Send className="size-4" /> Request review
            </Button>
          </DisabledReason>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" aria-label="More actions" data-testid="skill-more">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => void runExport()}>
                <Download className="size-4" /> Export SKILL.md
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  duplicate.mutate(s.id, {
                    onSuccess: (d) => {
                      toast.success(`Created ${d.name}`, { description: 'A draft copy with the same tests.' });
                      router.push(`/skills/${d.id}`);
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
              <DropdownMenuItem className="flex-col items-start text-destructive" disabled={live.length > 0} onClick={() => setDialog('delete')}>
                <span className="flex items-center gap-2">
                  <Trash2 className="size-4" /> Delete skill
                </span>
                {live.length > 0 && <span className="pl-6 text-xs text-muted-foreground">Pinned by a live agent</span>}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
        )
      }
    >
      <div className="flex flex-col gap-4">
        <ReadOnlyNotice noun="skills" />
        {s.pendingReview && (
          <Alert data-testid="skill-pending-review">
            <Inbox />
            <AlertTitle>
              v{s.pendingReview.version} is waiting in Reviews · {s.pendingReview.approvals} of {plural(s.pendingReview.needed, 'approval')}
            </AlertTitle>
            <AlertDescription>
              <span>
                Editing is paused until it is decided.{' '}
                <Link href={`/reviews?review=${s.pendingReview.id}`} className="underline underline-offset-2">
                  Open {s.pendingReview.id}
                </Link>
              </span>
            </AlertDescription>
          </Alert>
        )}
        {s.status === 'deprecated' && (
          <Alert>
            <Archive />
            <AlertTitle>Deprecated</AlertTitle>
            <AlertDescription>No agent can attach it. {s.usage.length ? `${plural(s.usage.length, 'agent')} still pin a version; detach or replace it there.` : ''}</AlertDescription>
          </Alert>
        )}
        <BuilderFieldset>
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
              {s.loading === 'on_match' && (
                <AttributeCard title="Use when" icon={BookOpen}>
                  <p className="text-sm">{s.useWhen}</p>
                </AttributeCard>
              )}
              <AttributeCard title="Tools and knowledge" icon={Wrench} testId="skill-scope-card">
                <div className="flex flex-col gap-3 text-sm">
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">Tools</div>
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
          {tab === 'instructions' && <InstructionsTab key={`${newest.version}-${newest.savedAt}`} skill={s} />}
          {tab === 'resources' && <ResourcesTab skill={s} />}
          {tab === 'tests' && <TestsTab skill={s} />}
          {tab === 'used_by' && <UsedByTab skill={s} />}
          {tab === 'versions' && <VersionsTab skill={s} onExport={runExport} />}
          {tab === 'activity' && <ActivityTab skill={s} />}
        </RecordLayout>
        </BuilderFieldset>
      </div>

      <RequestReviewDialog
        open={dialog === 'review'}
        onOpenChange={(o) => !o && setDialog(null)}
        skill={s}
        isPending={request.isPending}
        onSubmit={async (note) => {
          const d = await request.mutateAsync(note);
          announcePublish({ name: s.name, version: newest.version, live: !d.pendingReview, liveNote: 'Agents can attach it now.', decidedBy: `${plural(d.pendingReview?.needed ?? 1, 'approver')} from ${s.ownerTeam}`, reviewId: d.pendingReview?.id, openReview: (id) => router.push(`/reviews?review=${id}`) });
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
            router.push('/skills');
          } catch (e) {
            toast.error('Couldn’t delete the skill', { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
