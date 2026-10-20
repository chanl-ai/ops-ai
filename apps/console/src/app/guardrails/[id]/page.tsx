'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Archive, ArchiveRestore, MoreHorizontal, SearchX, Send, ShieldBan, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { GuardrailFields, guardrailErrors, keptScopes, type GuardrailDraft, type GuardrailErrors } from '@/components/guardrails/guardrail-fields';
import { PageLayout } from '@/components/page-layout';
import { BuilderFieldset, ReadOnlyNotice } from '@/components/shared/builder-only';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { SettingsSection } from '@/components/shared/settings-section';
import { VersionTimeline, VersionTimelineItem } from '@/components/shared/version-history';
import { announcePublish } from '@/components/shared/publish-result';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useDeleteGuardrail, useRequestGuardrailPublish, useSetGuardrailStatus, useUpdateGuardrail } from '@/hooks/guardrail-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useGuardrail } from '@/hooks/queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { ApiError } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import type { Guardrail } from '@/lib/types/domain';

const TABS = ['settings', 'versions'] as const;

const draftOf = (g: Guardrail): GuardrailDraft => ({ topics: g.config.topics, scopes: g.config.scopes ?? {}, message: g.config.message, holdUntilChecked: !!g.config.holdUntilChecked });

export default function GuardrailPage() {
  const { id } = useParams<{ id: string }>();
  const query = useGuardrail(id);
  if (query.isPending) return <RecordSkeleton />;
  if (query.isError)
    return (
      <PageLayout icon={ShieldBan} title="Guardrail" backHref="/guardrails">
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Guardrail not found" description="It may have been deleted, or the link is wrong." action={{ label: 'Back to guardrails', href: '/guardrails' }} />
        ) : (
          <QueryError what="this guardrail" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </PageLayout>
    );
  // Keyed by version, so the form reloads from the saved version after a save.
  return <GuardrailView key={`${query.data.id}-${query.data.version}`} guardrail={query.data} />;
}

function GuardrailView({ guardrail: g }: { guardrail: Guardrail }) {
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'settings');
  const canBuild = useCanBuild();
  const update = useUpdateGuardrail();
  const publish = useRequestGuardrailPublish();
  const setStatus = useSetGuardrailStatus();
  const remove = useDeleteGuardrail();
  const [draft, setDraft] = React.useState<GuardrailDraft>(() => draftOf(g));
  const [note, setNote] = React.useState('');
  const [errors, setErrors] = React.useState<GuardrailErrors>({});
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const saved = draftOf(g);
  const dirty = JSON.stringify([draft.topics, keptScopes(draft), draft.message.trim(), draft.holdUntilChecked]) !== JSON.stringify([saved.topics, keptScopes(saved), saved.message.trim(), saved.holdUntilChecked]);
  const canPublish = !g.pendingRequestId && g.publishedVersion !== g.version && g.status === 'live';
  const versions = g.versions ?? [];

  const save = async () => {
    const e = guardrailErrors(draft);
    setErrors(e);
    if (e.topics || e.message) return;
    try {
      const after = await update.mutateAsync({ id: g.id, topics: draft.topics, message: draft.message.trim(), scopes: keptScopes(draft), holdUntilChecked: draft.holdUntilChecked, note: note.trim() });
      toast.success(`Saved ${after.name} v${after.version} as a draft`, { description: 'Agents keep the version they pin. Publish it to let them pin this one.' });
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };
  const requestPublish = async () => {
    try {
      const after = await publish.mutateAsync(g);
      announcePublish({ name: g.name, version: g.version, live: after.publishedVersion === g.version, liveNote: 'Agents can pin it now.', decidedBy: `A reviewer in ${g.owner}`, reviewId: after.pendingRequestId, openReview: (id) => router.push(`/reviews?review=${id}`) });
    } catch (e) {
      toast.error(`Couldn’t publish ${g.name}`, { description: (e as Error).message });
    }
  };
  const toggleStatus = async () => {
    const next = g.status === 'live' ? 'deprecated' : 'live';
    try {
      await setStatus.mutateAsync({ id: g.id, status: next });
      toast.success(next === 'deprecated' ? `Deprecated ${g.name}` : `${g.name} is live again`, { description: next === 'deprecated' ? 'It takes no new pins; agents that pin it keep enforcing their version.' : undefined });
    } catch (e) {
      toast.error(`Couldn’t change ${g.name}`, { description: (e as Error).message });
    }
  };

  return (
    <PageLayout
      icon={ShieldBan}
      title={g.name}
      description={`Owned by ${g.owner} · newest v${g.version}${g.publishedVersion ? ` · published v${g.publishedVersion}` : ' · never published'}`}
      backHref="/guardrails"
      badge={g.status === 'deprecated' ? <Badge variant="outline">Deprecated</Badge> : <Badge variant="secondary">Live</Badge>}
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as (typeof TABS)[number])}>
          <TabsList>
            <TabsTrigger value="settings">Settings</TabsTrigger>
            <TabsTrigger value="versions" data-testid="guardrail-versions-tab">
              Versions · {versions.length}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      }
      actions={
        canBuild && (
          <>
            {g.pendingRequestId && (
              <Button variant="outline" asChild>
                <Link href={`/reviews?review=${g.pendingRequestId}`}>In review · v{g.version}</Link>
              </Button>
            )}
            {canPublish && (
              <LoadingButton variant="outline" isLoading={publish.isPending} loadingText="Sending…" disabled={dirty} title={dirty ? 'Save or discard your changes first' : undefined} onClick={requestPublish} data-testid="publish-guardrail">
                <Send className="size-4" /> Publish v{g.version}
              </LoadingButton>
            )}
            <LoadingButton isLoading={update.isPending} loadingText="Saving…" disabled={!dirty} onClick={save} data-testid="save-guardrail">
              Save as v{g.version + 1}
            </LoadingButton>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="More actions">
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={toggleStatus}>
                  {g.status === 'live' ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />} {g.status === 'live' ? 'Deprecate' : 'Make live'}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="text-destructive" disabled={g.usedBy.length > 0} onClick={() => setDeleteOpen(true)}>
                  <Trash2 className="size-4" /> Delete guardrail
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )
      }
    >
      <div className="flex flex-col gap-4">
        <ReadOnlyNotice noun="guardrails" />
        <RecordLayout
          rail={
            <AttributeCard title="Attributes" icon={ShieldBan}>
              <FieldRow label="Owner" value={g.owner} />
              <FieldRow label="Status" value={g.status === 'live' ? 'Live' : 'Deprecated'} />
              <FieldRow label="Newest" value={`v${g.version}`} />
              <FieldRow label="Published" value={g.publishedVersion ? `v${g.publishedVersion}` : undefined} emptyHint="Never" />
              <FieldRow label="Pinned by" value={g.usedBy.length ? g.usedBy.join(', ') : undefined} emptyHint="No agent" />
              <FieldRow label="Updated" value={relativeTime(g.updatedAt)} />
            </AttributeCard>
          }
        >
          {tab === 'versions' ? (
            <VersionTimeline testId="guardrail-versions">
              {versions.map((v) => (
                <VersionTimelineItem key={v.version} testId={`guardrail-version-${v.version}`} dot={v.version === g.publishedVersion ? 'success' : v.state === 'published' ? 'info' : 'muted'}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">v{v.version}</span>
                    {v.version === g.publishedVersion ? <Badge variant="secondary">Live for new pins</Badge> : <Badge variant="outline">{v.state === 'published' ? 'Published' : 'Draft'}</Badge>}
                    {v.note && <span className="text-sm font-medium">{v.note}</span>}
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Saved by {v.savedBy} · {relativeTime(v.savedAt)}
                    {v.publishedAt && ` · published ${relativeTime(v.publishedAt)}${v.publishedBy ? ` by ${v.publishedBy}` : ''}`}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">Blocks: {v.config.topics.join(', ')}</p>
                </VersionTimelineItem>
              ))}
            </VersionTimeline>
          ) : (
            <BuilderFieldset>
              <SettingsSection title="Rule" description={`Edits save v${g.version + 1} as a draft. Agents keep the version they pin; an agent picks any published version on its Guardrails section.`}>
                <div className="flex flex-col gap-4">
                  <GuardrailFields value={draft} onChange={(d) => (setDraft(d), setErrors({}))} errors={errors} />
                  {canBuild && (
                    <FormField id="guardrail-note" label="What changed" optional hint="Kept with the version and shown on the Versions tab.">
                      <Input id="guardrail-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Added a scope for savings products" />
                    </FormField>
                  )}
                </div>
              </SettingsSection>
            </BuilderFieldset>
          )}
        </RecordLayout>
      </div>
      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="guardrail"
        entityName={g.name}
        description="Refused while an agent pins it; unpin it on each agent first."
        confirmText="Delete guardrail"
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(g.id);
            toast.success(`Deleted ${g.name}`);
            router.push('/guardrails');
          } catch (e) {
            toast.error(`Couldn’t delete ${g.name}`, { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
