'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ExternalLink, Plug, Plus, SlidersHorizontal, Trash2, Unlink } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { RULE_FIELDS, RunStatusBadge, SensitivityBadge, SourceTypeIcon, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useAttachSources, useDetachSource, useSetKbSourceRules, useSourcesList } from '@/hooks/knowledge-queries';
import { useSticky } from '@/hooks/use-sticky';
import { count, plural, relativeTime } from '@/lib/format';
import type { KbSourceView, KnowledgeBaseDetail, Rule } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

type Row = KbSourceView & { onRowClick: (r: KbSourceView) => void };
const ALL = { page: 1, pageSize: 100 };

/** Which sources feed this knowledge base, and the rules narrowing what each one contributes. */
export function KbSourcesTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const router = useRouter();
  const allSources = useSourcesList(ALL);
  const attach = useAttachSources(kb.id);
  const detach = useDetachSource(kb.id);
  const setRules = useSetKbSourceRules(kb.id);
  const [attachOpen, setAttachOpen] = React.useState(false);
  const [picked, setPicked] = React.useState<string[]>([]);
  const [editing, setEditing] = React.useState<KbSourceView | null>(null);
  const editingShown = useSticky(editing);
  const [rules, setRulesDraft] = React.useState<Rule[]>([]);
  const [detaching, setDetaching] = React.useState<KbSourceView | null>(null);
  const detachingShown = useSticky(detaching);

  const openRules = React.useCallback((r: KbSourceView) => {
    setEditing(r);
    setRulesDraft(r.rules);
  }, []);
  const unattached = (allSources.data?.data ?? []).filter((s) => !kb.sources.some((l) => l.sourceId === s.id));
  const rows: Row[] = React.useMemo(() => kb.attached.map((a) => ({ ...a, onRowClick: openRules })), [kb.attached, openRules]);

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      {
        id: 'name',
        accessorFn: (r) => r.source.name,
        header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />,
        cell: ({ row }) => (
          <div className="flex min-w-48 items-center gap-2">
            <SourceTypeIcon type={row.original.source.type} />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.original.source.name}</div>
              <div className="truncate text-xs text-muted-foreground">
                {sourceTypeMeta(row.original.source.type).label} · {row.original.source.collection}
              </div>
            </div>
          </div>
        ),
        enableHiding: false,
      },
      { id: 'items', accessorFn: (r) => r.itemsContributed, header: ({ column }) => <DataTableColumnHeader column={column} title="Items contributed" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.itemsContributed)}</span> },
      {
        id: 'filter',
        header: () => <span className="text-xs">Filter</span>,
        cell: ({ row }) =>
          row.original.rules.length ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="cursor-default font-normal">
                  {plural(row.original.rules.length, 'rule')}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                {row.original.rules.map((r) => (
                  <div key={r.id} className="font-mono text-xs">
                    {r.kind} {r.field} {r.value}
                  </div>
                ))}
              </TooltipContent>
            </Tooltip>
          ) : (
            <Badge variant="secondary" className="font-normal">
              Everything
            </Badge>
          ),
      },
      { id: 'sensitivity', header: () => <span className="text-xs">Sensitivity</span>, cell: ({ row }) => <SensitivityBadge level={row.original.source.sensitivity} /> },
      { id: 'sync', accessorFn: (r) => r.source.lastSyncAt ?? '', header: ({ column }) => <DataTableColumnHeader column={column} title="Last sync" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.source.lastSyncAt)}</span> },
      { id: 'status', header: () => <span className="text-xs">Status</span>, cell: ({ row }) => <RunStatusBadge status={row.original.source.status === 'revoked' ? 'failed' : row.original.source.lastRunStatus} /> },
      {
        id: 'actions',
        meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
        cell: ({ row }) => (
          <StopRowClick>
            <DataTableRowActions
              row={row}
              actions={[
                { label: 'Edit contribution', icon: SlidersHorizontal, onClick: (r) => openRules(r.original) },
                { label: 'Open source', icon: ExternalLink, onClick: (r) => router.push(`/sources/${r.original.sourceId}`) },
                { label: 'Detach', icon: Unlink, variant: 'destructive', onClick: (r) => setDetaching(r.original) },
              ]}
            />
          </StopRowClick>
        ),
        enableHiding: false,
      },
    ],
    [openRules, router],
  );

  const lastWithPublicLink = kb.sources.length === 1 && kb.access.publicLink.enabled;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">Changing a source’s parsing or chunking reprocesses its items once; every knowledge base picks up the new chunks on its next refresh.</p>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.sourceId}
        searchColumn="name"
        searchPlaceholder="Search attached sources…"
        hideViewSwitcher
        toolbarExtra={
          <Button
            size="sm"
            onClick={() => {
              setPicked([]);
              setAttachOpen(true);
            }}
          >
            <Plus className="size-4" /> Attach sources
          </Button>
        }
        emptyState={
          <EmptyState
            icon={Plug}
            title="This knowledge base reads no sources"
            description="Attach a source and the next refresh indexes its items."
            action={{ label: 'Attach sources', onClick: () => setAttachOpen(true) }}
            secondaryAction={{ label: 'Open Sources', href: '/sources' }}
          />
        }
      />

      <DialogShell
        open={attachOpen}
        onOpenChange={setAttachOpen}
        size="md"
        title="Attach sources"
        description={`Sources ${kb.name} does not read yet. Their items are indexed on the next refresh.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setAttachOpen(false)} disabled={attach.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={attach.isPending}
              disabled={!picked.length}
              onClick={async () => {
                try {
                  await attach.mutateAsync(picked);
                  toast.success(`Attached ${plural(picked.length, 'source')}`, { description: 'Refresh the index to search them.' });
                  setAttachOpen(false);
                } catch (e) {
                  toast.error('Couldn’t attach', { description: (e as Error).message });
                }
              }}
            >
              {picked.length ? `Attach ${plural(picked.length, 'source')}` : 'Attach'}
            </LoadingButton>
          </div>
        }
      >
        {unattached.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Every source is already attached.{' '}
            <Link href="/sources" className="underline underline-offset-4">
              Add a new source
            </Link>
            .
          </p>
        ) : (
          <div className="divide-y rounded-md border">
            {unattached.map((s) => (
              <label key={s.id} htmlFor={`att-${s.id}`} className={cn('flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-accent/40', picked.includes(s.id) && 'bg-primary/5')}>
                <Checkbox id={`att-${s.id}`} checked={picked.includes(s.id)} onCheckedChange={(v) => setPicked((p) => (v ? [...p, s.id] : p.filter((x) => x !== s.id)))} />
                <SourceTypeIcon type={s.type} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{s.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {plural(s.itemsIndexed, 'item')} · {s.collection}
                  </span>
                </span>
                {kb.collections.length > 0 && !kb.collections.includes(s.collection) && (
                  <Badge variant="outline" className="font-normal text-amber-700 dark:text-amber-300">
                    Outside its collections
                  </Badge>
                )}
              </label>
            ))}
          </div>
        )}
      </DialogShell>

      <DialogShell
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        size="lg"
        title={`Contribution from ${editingShown?.source.name ?? 'source'}`}
        description={`Narrow what this source contributes to ${kb.name} only. The source’s own rules still apply first.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setEditing(null)} disabled={setRules.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={setRules.isPending}
              onClick={async () => {
                if (!editing) return;
                try {
                  await setRules.mutateAsync({ sourceId: editing.sourceId, rules: rules.filter((r) => r.value.trim()) });
                  toast.success('Contribution rules saved', { description: 'They apply on the next refresh.' });
                  setEditing(null);
                } catch (e) {
                  toast.error('Couldn’t save rules', { description: (e as Error).message });
                }
              }}
            >
              Save rules
            </LoadingButton>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          {rules.length === 0 && <p className="text-sm text-muted-foreground">No rules. Every item from this source is included.</p>}
          {rules.map((r, i) => (
            <div key={r.id} className="flex flex-wrap items-center gap-2">
              <Select value={r.kind} onValueChange={(v) => setRulesDraft(rules.map((x, j) => (j === i ? { ...x, kind: v as Rule['kind'] } : x)))}>
                <SelectTrigger className="h-8 w-28" aria-label="Include or exclude">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="include">Include</SelectItem>
                  <SelectItem value="exclude">Exclude</SelectItem>
                </SelectContent>
              </Select>
              <Select value={r.field} onValueChange={(v) => setRulesDraft(rules.map((x, j) => (j === i ? { ...x, field: v as Rule['field'] } : x)))}>
                <SelectTrigger className="h-8 w-40" aria-label="Field">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RULE_FIELDS.map((f) => (
                    <SelectItem key={f.value} value={f.value}>
                      {f.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input className="h-8 min-w-36 flex-1 font-mono text-xs" value={r.value} aria-label="Value" onChange={(e) => setRulesDraft(rules.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} placeholder="e.g. docs/changelog/**" />
              <Button variant="ghost" size="icon" className="size-8" onClick={() => setRulesDraft(rules.filter((_, j) => j !== i))} aria-label="Remove rule">
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" className="w-fit" onClick={() => setRulesDraft([...rules, { id: `kr${Date.now()}`, kind: 'exclude', field: 'path', value: '' }])}>
            <Plus className="size-3.5" /> Add rule
          </Button>
        </div>
      </DialogShell>

      <DialogShell
        open={!!detaching}
        onOpenChange={(o) => !o && setDetaching(null)}
        size="sm"
        title={lastWithPublicLink ? 'Can’t detach the last source' : `Detach ${detachingShown?.source.name}?`}
        description={
          lastWithPublicLink
            ? 'A knowledge base with a public link must keep at least one source. Turn the link off or attach another source first.'
            : `Chunks from this source leave ${kb.name} on the next refresh. The source and its items are kept${detachingShown && detachingShown.source.usedByKbIds.length <= 1 ? '; no other knowledge base reads it' : ''}.`
        }
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setDetaching(null)} disabled={detach.isPending}>
              {lastWithPublicLink ? 'Close' : 'Cancel'}
            </Button>
            {!lastWithPublicLink && (
              <LoadingButton
                variant="destructive"
                isLoading={detach.isPending}
                onClick={async () => {
                  const d = detaching!;
                  try {
                    await detach.mutateAsync(d.sourceId);
                    toast.success(`Detached ${d.source.name}`);
                    setDetaching(null);
                  } catch (e) {
                    toast.error('Couldn’t detach', { description: (e as Error).message });
                  }
                }}
              >
                Detach
              </LoadingButton>
            )}
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">Agents citing {kb.name} stop finding this source’s documents once the index refreshes.</p>
      </DialogShell>
    </div>
  );
}
