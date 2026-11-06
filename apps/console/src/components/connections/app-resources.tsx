'use client';

import * as React from 'react';

import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { useCan } from '@/hooks/me-queries';
import { Bot, FileText, Library, Sparkles, Workflow } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import {
  type AddBindings,
  type AddOutcome,
  type AppResource,
  type ResourceKind,
  type ResourcePlan,
  useAddResources,
  useAppResources,
  useRemoveCopy,
  useResourcePlan,
  useTakeUpdate,
  useUpdateReview,
  usersOf,
} from '@/hooks/app-resources-queries';
import { useKnowledgeBases } from '@/hooks/knowledge-queries';
import { useModelAliases } from '@/hooks/queries';
import { plural } from '@/lib/format';

const COPY_HREF: Record<ResourceKind, string> = {
  agent: '/agents',
  skill: '/skills',
  workflow: '/workflows',
  document_type: '/document-types',
  knowledge_source: '/knowledge/sources',
};
const ICON: Record<ResourceKind, typeof Bot> = { agent: Bot, skill: Sparkles, workflow: Workflow, document_type: FileText, knowledge_source: Library };
const KIND: Record<ResourceKind, string> = {
  agent: 'agent',
  skill: 'skill',
  workflow: 'workflow',
  document_type: 'document type',
  knowledge_source: 'knowledge source',
};
const USER_HREF: Record<string, string> = { workflow: '/workflows', agent: '/agents' };

const resourceOf = (r: { source: string; id: string }) => `${r.source}:${r.id}`;
const hrefOf = (kind: ResourceKind, recordId: string) => `${COPY_HREF[kind]}/${recordId}`;

function StateBadge({ r, app }: { r: AppResource; app: string }) {
  if (r.state === 'added') return <Badge variant="outline">Added</Badge>;
  if (r.state === 'update_available') return <Badge variant="outline">Update available</Badge>;
  if (r.state === 'removed_upstream') return <Badge variant="outline">{`No longer offered by ${app}`}</Badge>;
  if (r.state === 'needs_sign_in') return <Badge variant="outline">Sign in first</Badge>;
  return null;
}

/**
 * Resources: the agents, skills, workflows, document types and knowledge sources an app brings, each with its state for
 * the team from the API's one list. Each row can be ticked; Add selected previews what the ticked ones bring with them,
 * the bindings to fill and anything refused, then adds them in the preview's order. Add to team on a row is the same
 * flow with one item, made at once when it brings nothing else. An added copy opens, takes the app's update, or is
 * removed through its own delete.
 */
export function ResourcesTab({ appName, pluginId, onConnect }: { appName: string; pluginId?: string | null; onConnect?: () => void }) {
  const router = useRouter();
  const source = pluginId ? `plugin:${pluginId}` : '';
  const list = useAppResources(source);
  const plan = useResourcePlan();
  const add = useAddResources(source);
  // Adding an app's resources makes the team's own agents; a person who may not is told who adds them instead.
  const mayAdd = useCan('agents', 'create') !== false;
  const [ticked, setTicked] = React.useState<string[]>([]);
  const [preview, setPreview] = React.useState<ResourcePlan | null>(null);
  const [updating, setUpdating] = React.useState<AppResource | null>(null);
  const [removing, setRemoving] = React.useState<AppResource | null>(null);
  const rows = React.useMemo(() => list.data ?? [], [list.data]);
  // A ticked workflow brings the resources it cannot run without: they are ticked too, and cannot be unticked.
  const brought = React.useMemo(() => {
    const out = new Set<string>();
    for (const r of rows) if (ticked.includes(resourceOf(r))) for (const d of r.requires.resources ?? []) out.add(d);
    return out;
  }, [rows, ticked]);

  if (!pluginId)
    return (
      <Section>
        <p className="text-sm text-muted-foreground" data-testid="app-skills-none">
          No resources: {appName} brings tools only.
        </p>
      </Section>
    );

  // Add selected always previews; Add to team on a row previews only when the resource brings others or needs a pick.
  const start = (resources: string[], { preview: always = false }: { preview?: boolean } = {}) =>
    plan.mutate(resources, {
      onSuccess: (p) => {
        const toMake = p.items.filter((i) => !i.heldRecordId);
        const [only] = toMake;
        // One resource bringing nothing else, refused for nothing and needing no pick: made at once, then opened.
        if (!always && toMake.length === 1 && only && !only.refusal && only.service !== 'kb' && resources.length === 1) {
          add.mutate(
            { plan: p, bindings: { names: {} } },
            {
              onSuccess: ([made]) => {
                if (made?.error) toast.error(`Couldn’t add ${only.title}`, { description: made.error.message });
                else if (made?.recordId) {
                  toast.success(`Added ${only.title} to your team`);
                  router.push(hrefOf(made.kind, made.recordId));
                }
              },
            },
          );
        } else if (toMake.length === 0) {
          toast.info('Your team already has these.');
        } else setPreview(p);
      },
      onError: (e) => toast.error('Couldn’t preview these resources', { description: e.message }),
    });

  const busy = (r: AppResource) => (plan.isPending || add.isPending) && plan.variables?.includes(resourceOf(r));
  const selected = ticked.filter((t) => rows.some((r) => resourceOf(r) === t && r.canAdd));

  return (
    <Section
      title="Resources"
      description="Agents, skills, workflows, document types and knowledge sources the app brings. Added ones are your team’s own copies."
      flush
      actions={
        mayAdd ? (
        <LoadingButton
          size="sm"
          variant="outline"
          disabled={selected.length === 0}
          isLoading={plan.isPending && (plan.variables?.length ?? 0) > 1}
          onClick={() => start([...new Set([...selected, ...brought])], { preview: true })}
          data-testid="resources-add-selected"
        >
          {selected.length ? `Add selected (${selected.length})` : 'Add selected'}
        </LoadingButton>
        ) : (
          <AskAnAdmin testId="resources-why" area="agents" action="create" lead="Builders and admins add these to the team." />
        )
      }
    >
      {list.isPending ? (
        <div className="flex flex-col gap-2 p-4" aria-busy="true">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : list.isError ? (
        <div className="p-4">
          <QueryError what="the app’s resources" error={list.error} onRetry={() => void list.refetch()} retrying={list.isFetching} />
        </div>
      ) : rows.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground" data-testid="app-skills-none">
          No resources: {appName} brings tools only.
        </p>
      ) : (
        <Rows testId="app-skills">
          {rows.map((r) => {
            const Icon = ICON[r.kind];
            const id = resourceOf(r);
            const forced = brought.has(id);
            const addable = r.canAdd && r.state === 'available';
            return (
              <Row
                key={id}
                wrap
                leading={
                  <span className="flex items-center gap-3">
                    <Checkbox
                      aria-label={`Choose ${r.title}`}
                      checked={forced || ticked.includes(id)}
                      disabled={!addable || forced}
                      onCheckedChange={(on) => setTicked((t) => (on ? [...t, id] : t.filter((x) => x !== id)))}
                      data-testid={`resource-pick-${r.id}`}
                    />
                    <Icon className="size-4 text-muted-foreground" />
                  </span>
                }
                title={
                  <span className="flex flex-wrap items-center gap-2" data-testid={`resource-${r.id}`}>
                    {r.title}
                    <Badge variant="secondary">{KIND[r.kind]}</Badge>
                    <StateBadge r={r} app={appName} />
                  </span>
                }
                description={!r.canAdd && r.reason && (r.state === 'available' || r.state === 'needs_sign_in') ? r.reason : undefined}
                trailing={
                  <span className="flex flex-wrap items-center gap-2">
                    {addable && (
                      <LoadingButton size="sm" variant="outline" isLoading={busy(r)} onClick={() => start([id])} data-testid={`resource-add-${r.id}`}>
                        {r.kind === 'knowledge_source' ? 'Add to a knowledge base' : 'Add to team'}
                      </LoadingButton>
                    )}
                    {r.state === 'needs_sign_in' && !r.reason && onConnect && (
                      <Button size="sm" variant="outline" onClick={onConnect} data-testid={`resource-connect-${r.id}`}>
                        Connect
                      </Button>
                    )}
                    {r.state === 'update_available' && r.copy && (
                      <Button size="sm" variant="outline" onClick={() => setUpdating(r)} data-testid={`resource-update-${r.id}`}>
                        Review update
                      </Button>
                    )}
                    {r.copy && (
                      <Button size="sm" variant="ghost" asChild>
                        <Link href={hrefOf(r.kind, r.copy.recordId)} data-testid={`resource-open-${r.id}`}>
                          Open
                        </Link>
                      </Button>
                    )}
                    {r.copy && r.canRemove && (
                      <Button size="sm" variant="ghost" onClick={() => setRemoving(r)} data-testid={`resource-remove-${r.id}`}>
                        Remove
                      </Button>
                    )}
                  </span>
                }
              />
            );
          })}
        </Rows>
      )}
      {preview && (
        <AddPreviewDialog
          plan={preview}
          onOpenChange={(o) => {
            if (!o) {
              setPreview(null);
              add.reset();
            }
          }}
          adding={add.isPending}
          outcomes={add.data}
          onAdd={(bindings) => add.mutate({ plan: preview, bindings }, { onSuccess: () => setTicked([]) })}
        />
      )}
      {updating && <UpdateDialog resource={updating} app={source} onOpenChange={(o) => !o && setUpdating(null)} />}
      {removing && <RemoveDialog resource={removing} app={source} onOpenChange={(o) => !o && setRemoving(null)} />}
    </Section>
  );
}

function AddPreviewDialog({
  plan,
  onOpenChange,
  adding,
  outcomes,
  onAdd,
}: {
  plan: ResourcePlan | null;
  onOpenChange: (open: boolean) => void;
  adding: boolean;
  outcomes?: AddOutcome[];
  onAdd: (bindings: AddBindings) => void;
}) {
  const aliases = useModelAliases();
  const bases = useKnowledgeBases({ page: 1, pageSize: 100 });
  const [knowledgeBase, setKnowledgeBase] = React.useState<string>('');
  const [modelAlias, setModelAlias] = React.useState<string>('');
  const [names, setNames] = React.useState<Record<string, string>>({});
  React.useEffect(() => {
    setNames(Object.fromEntries((plan?.items ?? []).flatMap((i) => (i.refusal?.suggestion ? [[i.resource, i.refusal.suggestion]] : []))));
    setKnowledgeBase('');
    setModelAlias('');
  }, [plan]);
  if (!plan) return null;
  const items = plan.items;
  const toMake = items.filter((i) => !i.heldRecordId);
  const needsBase = toMake.some((i) => i.bindings.some((b) => 'knowledgeBase' in b));
  const needsAlias = toMake.some((i) => i.bindings.some((b) => 'modelAlias' in b));
  const needsBasePick = toMake.some((i) => i.service === 'kb');
  const blocked = toMake.some((i) => i.refusal && i.refusal.code !== 'name_taken');
  const done = !!outcomes;
  const failed = outcomes?.find((o) => o.error);
  return (
    <DialogShell
      open
      onOpenChange={onOpenChange}
      size="lg"
      title={done ? (failed ? 'Some resources were not added' : `Added ${plural(outcomes.length, 'resource')}`) : `Add ${plural(toMake.length, 'resource')} to your team`}
      description={done ? undefined : 'Each one is made in this order, through the same checks as making it yourself.'}
      onSubmit={done ? undefined : () => onAdd({ knowledgeBase: knowledgeBase || undefined, modelAlias: modelAlias || undefined, names })}
      footer={
        done ? (
          <Button type="button" onClick={() => onOpenChange(false)} data-testid="resources-preview-done">
            Done
          </Button>
        ) : (
          <div className="flex w-full justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={adding} disabled={blocked || (needsBasePick && !knowledgeBase)} data-testid="resources-preview-add">
              {`Add ${plural(toMake.length, 'resource')}`}
            </LoadingButton>
          </div>
        )
      }
    >
      {done ? (
        <ul className="flex flex-col divide-y" data-testid="resources-added">
          {outcomes.map((o) => (
            <li key={o.item.resource} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <span className="min-w-0">
                {o.item.title}
                {o.error && <span className="block text-destructive-text">{o.error.message}</span>}
              </span>
              {o.recordId && o.kind !== 'knowledge_source' && (
                <Button size="sm" variant="ghost" asChild>
                  <Link href={hrefOf(o.kind, o.recordId)}>Open</Link>
                </Button>
              )}
            </li>
          ))}
          {failed && outcomes.some((o) => o.recordId) && (
            <li className="py-2 text-sm text-muted-foreground">The ones made before it are drafts of your team’s; open or remove each from its row.</li>
          )}
        </ul>
      ) : (
        <div className="flex flex-col gap-4">
          <ul className="flex flex-col divide-y" data-testid="resources-preview">
            {items.map((i) => (
              <li key={i.resource} className="flex flex-col gap-1 py-2 text-sm">
                <span className="flex flex-wrap items-center gap-2 font-medium">
                  {i.title}
                  <Badge variant="secondary">{KIND[i.kind]}</Badge>
                  {i.heldRecordId && <Badge variant="outline">Already in your team</Badge>}
                </span>
                {i.broughtBy.length > 0 && (
                  <span className="text-muted-foreground">{`Needed by ${i.broughtBy.map((b) => items.find((x) => x.resource === b)?.title ?? b).join(', ')}`}</span>
                )}
                {i.heldRecordId && <span className="text-muted-foreground">Your team’s copy is used as it is.</span>}
                {!i.heldRecordId && i.tools.length > 0 && <span className="text-muted-foreground">{`Uses ${i.tools.join(', ')}`}</span>}
                {i.refusal && i.refusal.code !== 'name_taken' && <span className="text-destructive-text">{i.refusal.message}</span>}
                {i.refusal?.code === 'name_taken' && (
                  <FormField id={`name-${i.resource}`} label="Name" hint={i.refusal.message}>
                    <Input
                      id={`name-${i.resource}`}
                      value={names[i.resource] ?? ''}
                      onChange={(e) => setNames((n) => ({ ...n, [i.resource]: e.target.value }))}
                    />
                  </FormField>
                )}
              </li>
            ))}
          </ul>
          {(needsBase || needsBasePick) && (
            <FormField id="resources-kb" label="Knowledge base" optional={!needsBasePick} hint={needsBasePick ? undefined : 'Left empty, each copy asks for one before it is published.'}>
              <Select value={knowledgeBase} onValueChange={setKnowledgeBase}>
                <SelectTrigger id="resources-kb" data-testid="resources-kb">
                  <SelectValue placeholder={bases.isPending ? 'Loading knowledge bases' : 'Choose a knowledge base'} />
                </SelectTrigger>
                <SelectContent>
                  {(bases.data?.data ?? []).map((k) => (
                    <SelectItem key={k.id} value={k.id}>
                      {k.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
          {needsAlias && (
            <FormField id="resources-model" label="Model" optional hint="Left empty, each agent asks for one before it is published.">
              <Select value={modelAlias} onValueChange={setModelAlias}>
                <SelectTrigger id="resources-model" data-testid="resources-model">
                  <SelectValue placeholder={aliases.isPending ? 'Loading models' : 'Choose a model'} />
                </SelectTrigger>
                <SelectContent>
                  {(aliases.data ?? []).map((a) => (
                    <SelectItem key={a.name} value={a.name}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
        </div>
      )}
    </DialogShell>
  );
}

function UpdateDialog({ resource, app, onOpenChange }: { resource: AppResource | null; app: string; onOpenChange: (open: boolean) => void }) {
  const id = resource ? resourceOf(resource) : '';
  const review = useUpdateReview(id, resource?.copy?.recordId, resource?.kind ?? 'agent');
  const take = useTakeUpdate(app);
  const [confirmed, setConfirmed] = React.useState(false);
  React.useEffect(() => {
    setConfirmed(false);
  }, [resource]);
  if (!resource?.copy) return null;
  const r = review.data;
  const edited = (r?.edits.length ?? 0) > 0;
  return (
    <DialogShell
      open
      onOpenChange={onOpenChange}
      size="md"
      title={`Update ${resource.title}`}
      description="Taking the update makes a new version of your team’s copy. What runs now keeps running until that version is published."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={take.isPending}
            disabled={!r || (edited && !confirmed)}
            onClick={() =>
              take.mutate(
                { resource: id, copy: resource.copy!.recordId, confirm: edited, kind: resource.kind },
                {
                  onSuccess: () => {
                    toast.success(`A new version of ${resource.title} is ready`);
                    onOpenChange(false);
                  },
                  onError: (e) => toast.error(`Couldn’t update ${resource.title}`, { description: e.message }),
                },
              )
            }
            data-testid="resource-take-update"
          >
            Take update
          </LoadingButton>
        </div>
      }
    >
      {review.isPending ? (
        <Skeleton className="h-16 w-full" />
      ) : review.isError ? (
        <QueryError what="the update" error={review.error} onRetry={() => void review.refetch()} retrying={review.isFetching} />
      ) : (
        r && (
          <div className="flex flex-col gap-3 text-sm">
            <p>{r.changes.length ? `The update changes: ${r.changes.join(', ')}.` : 'The update changes nothing your copy shows.'}</p>
            {edited && (
              <>
                <p className="text-destructive-text">{`Your team changed ${r.edits.join(', ')} since adding it. The new version does not carry those changes.`}</p>
                <label className="flex items-center gap-2">
                  <Checkbox checked={confirmed} onCheckedChange={(on) => setConfirmed(on === true)} data-testid="resource-update-confirm" />
                  Take the update without my team’s changes
                </label>
              </>
            )}
          </div>
        )
      )}
    </DialogShell>
  );
}

function RemoveDialog({ resource, app, onOpenChange }: { resource: AppResource | null; app: string; onOpenChange: (open: boolean) => void }) {
  const remove = useRemoveCopy(app);
  React.useEffect(() => {
    remove.reset();
  }, [resource]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!resource?.copy) return null;
  const users = usersOf(remove.error);
  return (
    <DeleteDialog
      open
      onOpenChange={onOpenChange}
      entityType={KIND[resource.kind]}
      entityName={resource.title}
      verb="Remove"
      testIdPrefix="resource-remove"
      isLoading={remove.isPending}
      description={`Removes your team’s copy of ${resource.title}. The app’s template stays available to add again.`}
      onConfirm={() =>
        remove.mutateAsync({ kind: resource.kind, recordId: resource.copy!.recordId }).then(
          () => {
            toast.success(`Removed ${resource.title}`);
            onOpenChange(false);
          },
          (e: Error) => {
            if (!usersOf(e).length) toast.error(`Couldn’t remove ${resource.title}`, { description: e.message });
          },
        )
      }
    >
      {users.length > 0 && (
        <div className="flex flex-col gap-2 text-sm" data-testid="resource-remove-used-by">
          <p className="text-destructive-text">{remove.error?.message}</p>
          <ul className="flex flex-col gap-1">
            {users.map((u) => (
              <li key={u.id} className="flex items-center justify-between gap-2">
                {u.name}
                {USER_HREF[u.kind] && (
                  <Button size="sm" variant="ghost" asChild>
                    <Link href={`${USER_HREF[u.kind]}/${u.id}`}>Open to change or remove</Link>
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </DeleteDialog>
  );
}
