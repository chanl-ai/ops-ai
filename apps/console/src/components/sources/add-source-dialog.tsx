'use client';

import * as React from 'react';
import { Info, Loader2, Pencil, Plug, Plus, Trash2 } from 'lucide-react';

import { ConnectionChip, SystemMark } from '@/components/integrations/integration-meta';
import { RULE_FIELDS, RULE_PLACEHOLDER, SOURCE_TYPES, scheduleLabel, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload, type UploadItem, uploadsBlocker } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Stepper } from '@/components/shared/stepper';
import { KeyValues } from '@/components/shared/surface';
import { TagInput } from '@/components/shared/tag-input';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { bytes, count, plural } from '@/lib/format';
import type { ConnectionRef, IntegrationKind } from '@/lib/types/integrations';
import type { HeldPreview, HeldPreviewInput, KnowledgeBase, MetadataMapping, ParsingSettings, Rule, Schedule, Sensitivity, SourceInput, SourcePreview, SourceType } from '@/lib/types/knowledge';
import type { IngestPresetId, IngestSettings, SampleDocument, SplitPreview, SplitPreviewInput } from '@/lib/types/knowledge-ingest';
import { cn } from '@/lib/utils';

import { IngestForm } from './ingest-form';
import { applyPreset, defaultIngest, PRESET_LABEL, strategyMeta } from './ingest-meta';
import { MetadataMappingEditor } from './metadata-mapping-editor';
import { countFor, ScopeTree, TREES } from './scope-tree';
import { SplitPreviewPanel } from './split-preview';

const STEPS = ['Type', 'Scope', 'Ingestion', 'Rules', 'Schedule', 'Review'] as const;
const STEP_TITLE = ['Source type', 'Connection and scope', 'Ingestion', 'Rules and metadata', 'Permissions and schedule', 'Review'];

interface Draft {
  type?: SourceType;
  name: string;
  connectionId: string;
  scope: string[];
  urls: string;
  startUrl: string;
  depth: number;
  maxPages: number;
  includePaths: string;
  excludePaths: string;
  text: string;
  files: UploadItem[];
  parsing: ParsingSettings;
  ingest: IngestSettings;
  rules: Rule[];
  mapping: MetadataMapping[];
  tags: string[];
  titleFrom: 'source' | 'heading' | 'filename';
  sensitivity: Sensitivity;
  collection: string;
  permissions: 'inherit' | 'workspace' | 'selected';
  principals: string[];
  schedule: Schedule;
  deletedAtSource: 'remove' | 'keep_stale';
  staleAfter: number;
  notify: boolean;
  kbIds: string[];
}

const empty = (): Draft => ({
  name: '',
  connectionId: '',
  scope: [],
  urls: '',
  startUrl: '',
  depth: 2,
  maxPages: 200,
  includePaths: '',
  excludePaths: '',
  text: '',
  files: [],
  parsing: { ocr: false, tables: true, vision: false },
  ingest: defaultIngest(),
  rules: [],
  mapping: [{ key: 'locale', from: 'static:en' }],
  tags: [],
  titleFrom: 'source',
  sensitivity: 'internal',
  collection: '',
  permissions: 'workspace',
  principals: [],
  schedule: { kind: 'manual' },
  deletedAtSource: 'remove',
  staleAfter: 90,
  notify: true,
  kbIds: [],
});

/** The integration kind each connected-app source type reads through. */
const KIND_OF: Partial<Record<SourceType, IntegrationKind>> = { sharepoint: 'sharepoint', confluence: 'confluence', gdrive: 'gdrive', github: 'github', notion: 'notion', zendesk: 'zendesk', salesforce: 'salesforce' };
const usableConn = (c: ConnectionRef) => c.status === 'healthy' || c.status === 'expiring';

/** The preset a new source of this type starts from; web and help-centre content gets cleaned and FAQ questions. */
const presetFor = (t: SourceType): IngestPresetId => (t === 'crawl' || t === 'url' || t === 'zendesk' || t === 'salesforce' ? 'help_centre' : 'policy_manual');

const scheduleFor = (kind: Schedule['kind']): Schedule =>
  kind === 'manual' ? { kind } : kind === 'daily' ? { kind, time: '02:00' } : kind === 'weekly' ? { kind, day: 'Mon', time: '03:00' } : kind === 'monthly' ? { kind, day: 1, time: '03:00' } : { kind: 'webhook', safetyNetDaily: true };

function Tip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Info className="size-3.5 text-muted-foreground" />
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{text}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Add a source in six steps. Creating opens the source's page, where every setting stays editable; a draft can
 * be saved from step 2 onward and finished later.
 */
export function AddSourceDialog({
  open,
  onOpenChange,
  initialType,
  connections,
  newConnectionId,
  knowledgeBases,
  collections,
  existingNames,
  onPreview,
  onConnectNew,
  onSubmit,
  isPending,
  samples,
  samplesLoading,
  onPreviewSplit,
  onPreviewHeld,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialType?: SourceType;
  /** Connections from Integrations; a connected-app source must pick one. */
  connections: ConnectionRef[];
  /** Set after "Connect a new system" finishes, so the new connection is picked. */
  newConnectionId?: string;
  knowledgeBases: Pick<KnowledgeBase, 'id' | 'name'>[];
  collections: string[];
  existingNames: string[];
  onPreview: (input: Pick<SourceInput, 'type' | 'config'>) => Promise<SourcePreview>;
  /** Opens the Integrations connect dialog for this kind of system. */
  onConnectNew: (kind: IntegrationKind) => void;
  onSubmit: (input: SourceInput, opts: { sync: boolean; kbIds: string[] }) => Promise<unknown>;
  isPending: boolean;
  samples: SampleDocument[];
  samplesLoading?: boolean;
  onPreviewSplit: (input: SplitPreviewInput) => Promise<SplitPreview>;
  onPreviewHeld: (input: HeldPreviewInput) => Promise<HeldPreview>;
}) {
  const [step, setStep] = React.useState(1);
  const [d, setD] = React.useState<Draft>(empty);
  const [touched, setTouched] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<SourcePreview | null>(null);
  const [previewing, setPreviewing] = React.useState(false);
  const [held, setHeld] = React.useState<HeldPreview | null>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  // Read through a ref so a refetched connection list does not reset the draft mid-edit.
  const connectionsRef = React.useRef(connections);
  connectionsRef.current = connections;
  const pickType = React.useCallback((t: SourceType) => {
    const m = sourceTypeMeta(t);
    setD((x) => ({
      ...x,
      type: t,
      connectionId: connectionsRef.current.find((c) => c.kind === KIND_OF[t] && usableConn(c))?.id ?? '',
      scope: [],
      ingest: applyPreset(defaultIngest(), presetFor(t)),
      permissions: m.supportsInherit ? 'inherit' : 'workspace',
      schedule: t === 'file' || t === 'text' ? { kind: 'manual' } : m.supportsWebhook ? { kind: 'webhook', safetyNetDaily: true } : { kind: 'daily', time: '02:00' },
    }));
    setPreview(null);
  }, []);

  React.useEffect(() => {
    if (!open) return;
    setStep(initialType ? 2 : 1);
    setD(empty());
    if (initialType) pickType(initialType);
    setTouched(false);
    setSubmitError(null);
    setPreview(null);
  }, [open, initialType, pickType]);
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);
  React.useEffect(() => {
    if (newConnectionId) setD((x) => ({ ...x, connectionId: newConnectionId }));
  }, [newConnectionId]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const meta = d.type ? sourceTypeMeta(d.type) : undefined;
  const kindConns = d.type && KIND_OF[d.type] ? connections.filter((c) => c.kind === KIND_OF[d.type!]) : [];
  const conn = kindConns.find((c) => c.id === d.connectionId);
  const needsConnection = !!meta?.connected && !(conn && usableConn(conn));
  const tree = d.type ? TREES[d.type] : undefined;
  const scopeCount = tree ? countFor(tree, d.scope) : 0;
  const urlList = d.urls.split('\n').map((u) => u.trim()).filter(Boolean);
  const config = (): Record<string, unknown> => ({
    scope: d.scope,
    scopeCount,
    urls: d.urls,
    startUrl: d.startUrl,
    depth: d.depth,
    maxPages: d.maxPages,
    include: d.includePaths,
    exclude: d.excludePaths,
    fileNames: d.files.map((f) => f.name),
    fileIds: d.files.map((f) => f.fileId).filter(Boolean),
  });

  // Required keys of the chosen knowledge bases and how many previewed items they would hold, from the API.
  const heldKey = JSON.stringify([d.type, d.kbIds, d.mapping, d.files.length, d.urls, d.scope, step >= 4]);
  React.useEffect(() => {
    if (!d.type || step < 4 || !d.kbIds.length) {
      setHeld(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      onPreviewHeld({ type: d.type!, config: config(), metadataMapping: d.mapping.filter((m) => m.key.trim()), kbIds: d.kbIds })
        .then((r) => {
          if (live) setHeld(r);
        })
        .catch(() => {
          if (live) setHeld(null);
        });
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heldKey]);
  const heldTotal = held?.byKb.filter((k) => k.held > 0) ?? [];

  const errors: Record<number, string | undefined> = {
    1: d.type ? undefined : 'Pick a source type.',
    2: (() => {
      if (d.name.trim().length < 2 || d.name.length > 80) return 'Name it in 2 to 80 characters, e.g. Card dispute policies.';
      if (existingNames.some((n) => n.toLowerCase() === d.name.trim().toLowerCase())) return 'A source with this name already exists.';
      if (needsConnection) return conn ? `${conn.name} is not healthy. Pick another connection or fix it in Integrations.` : `Pick a ${meta?.label} connection, or connect one.`;
      if (tree && !d.scope.length) return `Pick at least one item under ${meta?.scopeLabel.toLowerCase()}.`;
      if (d.type === 'url' && !urlList.length) return 'Add at least one URL.';
      if (d.type === 'url' && urlList.some((u) => !/^https?:\/\//.test(u))) return 'URLs start with http:// or https://.';
      if (d.type === 'crawl' && !/^https?:\/\//.test(d.startUrl)) return 'The start URL starts with http:// or https://.';
      if (d.type === 'crawl' && (d.depth < 1 || d.depth > 5)) return 'Depth is 1 to 5.';
      if (d.type === 'crawl' && (d.maxPages < 10 || d.maxPages > 5000)) return 'Max pages is 10 to 5,000.';
      if (d.type === 'text' && !d.text.trim()) return 'Paste the text to index.';
      if (d.type === 'file' && !d.files.length) return 'Add at least one file.';
      if (d.type === 'file' && uploadsBlocker(d.files)) return uploadsBlocker(d.files);
      if (preview && !preview.ok) return preview.message;
      return undefined;
    })(),
    3: !d.ingest.strategies.length
      ? 'Choose at least one strategy, or a preset.'
      : d.ingest.strategies.includes('table_rows') && d.ingest.columns.length && !d.ingest.columns.some((c) => c.role === 'searchable')
        ? 'Mark at least one table column as searchable.'
        : d.ingest.size < 100 || d.ingest.size > 2000
          ? 'Chunk size is 100 to 2,000 tokens.'
          : undefined,
    5: d.permissions === 'selected' && !d.principals.length ? 'Add at least one member or group.' : undefined,
  };
  const stepError = touched ? errors[step] : undefined;
  const next = () => {
    if (errors[step]) {
      setTouched(true);
      // The error sits at the top of the body; an inline one next to its control is shown first when there is one.
      requestAnimationFrame(() => {
        const inline = bodyRef.current?.querySelector('[data-field-error]');
        if (inline) inline.scrollIntoView({ block: 'center', behavior: 'smooth' });
        else bodyRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
      });
      return;
    }
    setTouched(false);
    setStep(step + 1);
  };

  const scopeSummary =
    d.type === 'file'
      ? plural(d.files.length, 'file')
      : d.type === 'url'
        ? plural(urlList.length, 'URL')
        : d.type === 'crawl'
          ? `${d.startUrl} · depth ${d.depth} · ${count(d.maxPages)} pages max`
          : d.type === 'text'
            ? `Pasted Markdown · ${plural(d.text.split(/\s+/).filter(Boolean).length, 'word')}`
            : `${d.scope.length} ${meta?.scopeLabel.toLowerCase()} selected · about ${plural(scopeCount, 'item')}`;

  const build = (status: 'active' | 'draft'): SourceInput => ({
    type: d.type!,
    name: d.name.trim(),
    connectionId: meta?.connected ? d.connectionId || undefined : undefined,
    status,
    scopeSummary,
    config: config(),
    parsing: d.parsing,
    ingest: d.ingest,
    rules: d.rules.filter((r) => r.value.trim()),
    metadataMapping: d.mapping.filter((m) => m.key.trim()),
    tags: d.tags,
    titleFrom: d.titleFrom,
    permissions: d.permissions === 'selected' ? { mode: 'selected', principals: d.principals } : { mode: d.permissions },
    schedule: d.schedule,
    deletedAtSource: d.deletedAtSource,
    staleAfterDays: d.staleAfter,
    notifyOnFailure: d.notify,
    sensitivity: d.sensitivity,
    collection: d.collection.trim() || 'General',
    fileIds: d.type === 'file' ? d.files.flatMap((f) => (f.fileId ? [f.fileId] : [])) : undefined,
    itemsPending: preview?.rows.length ?? (d.type === 'file' ? d.files.length : d.type === 'url' ? urlList.length : d.type === 'text' ? 1 : scopeCount),
  });

  const submit = async (status: 'active' | 'draft', sync: boolean) => {
    setSubmitError(null);
    try {
      await onSubmit(build(status), { sync, kbIds: status === 'draft' ? [] : d.kbIds });
      onOpenChange(false);
    } catch (e) {
      setSubmitError((e as Error).message);
      if (status === 'draft') setTouched(true);
    }
  };

  const runPreview = async () => {
    if (!d.type) return;
    setPreviewing(true);
    try {
      setPreview(await onPreview({ type: d.type, config: config() }));
    } catch (e) {
      setPreview({ ok: false, message: (e as Error).message, rows: [] });
    } finally {
      setPreviewing(false);
    }
  };

  const ruleRow = (r: Rule, i: number) => (
    <div key={r.id} className="flex flex-wrap items-center gap-2">
      <Select value={r.kind} onValueChange={(v) => set('rules', d.rules.map((x, j) => (j === i ? { ...x, kind: v as Rule['kind'] } : x)))}>
        <SelectTrigger className="h-8 w-28" aria-label="Include or exclude">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="include">Include</SelectItem>
          <SelectItem value="exclude">Exclude</SelectItem>
        </SelectContent>
      </Select>
      <Select value={r.field} onValueChange={(v) => set('rules', d.rules.map((x, j) => (j === i ? { ...x, field: v as Rule['field'] } : x)))}>
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
      <Input
        className="h-8 min-w-40 flex-1 font-mono text-xs"
        value={r.value}
        aria-label="Value"
        placeholder={RULE_PLACEHOLDER[r.field]}
        onChange={(e) => set('rules', d.rules.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
      />
      <Button variant="ghost" size="icon" className="size-8" onClick={() => set('rules', d.rules.filter((_, j) => j !== i))} aria-label="Remove rule">
        <Trash2 className="size-3.5" />
      </Button>
    </div>
  );

  const reviewSections: [string, number, [string, React.ReactNode][]][] = meta
    ? [
        ['Source type', 1, [['Type', meta.label]]],
        ['Connection and scope', 2, [['Name', d.name], ['Connection', conn?.name], ['Scope', scopeSummary]]],
        [
          'Ingestion',
          3,
          [
            ['Preset', PRESET_LABEL[d.ingest.preset]],
            ['Strategies', d.ingest.strategies.map((x) => strategyMeta(x).label).join(', ')],
            ['Parsing', [d.parsing.ocr && 'OCR', d.parsing.tables && 'keep tables', d.parsing.vision && 'vision'].filter(Boolean).join(', ') || 'Defaults'],
            ['Chunks', `${d.ingest.size} tokens · ${d.ingest.overlap} overlap`],
            ...(d.ingest.strategies.some((x) => strategyMeta(x).ai) ? [['AI steps', `Call ${d.ingest.model}; wait for the knowledge owner’s approval`] as [string, string]] : []),
          ],
        ],
        [
          'Rules and metadata',
          4,
          [
            ['Rules', d.rules.filter((r) => r.value).map((r) => `${r.kind} ${r.field} ${r.value}`).join('; ') || 'None'],
            ['Metadata', d.mapping.filter((m) => m.key).map((m) => `${m.key} ← ${m.from.replace(/^(static|field):/, '')}`).join(', ') || 'None'],
            ['Tags', d.tags.join(', ') || 'None'],
            ['Knowledge bases', knowledgeBases.filter((k) => d.kbIds.includes(k.id)).map((k) => k.name).join(', ') || 'None'],
            ['Collection', d.collection || 'General'],
            ['Sensitivity', d.sensitivity],
          ],
        ],
        [
          'Permissions and schedule',
          5,
          [
            ['Permissions', d.permissions === 'inherit' ? `Inherit from ${meta.short}` : d.permissions === 'workspace' ? 'Workspace-wide' : d.principals.join(', ')],
            ['Schedule', scheduleLabel(d.schedule)],
            ['Deleted at source', d.deletedAtSource === 'remove' ? 'Remove from index' : 'Keep and mark stale'],
            ['Stale after', `${d.staleAfter} days`],
          ],
        ],
      ]
    : [];

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Add source"
      description={`Step ${step} of ${STEPS.length} · ${STEP_TITLE[step - 1]}`}
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="source-stepper" />}
      bodyRef={bodyRef}
      bodyClassName="h-[30rem] flex-auto"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <div>
            {step > 1 && step < STEPS.length && (
              <Button variant="ghost" onClick={() => submit('draft', false)} disabled={isPending || d.name.trim().length < 2}>
                Save as draft
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => (step === 1 ? onOpenChange(false) : (setTouched(false), setStep(step - 1)))} disabled={isPending}>
              {step === 1 ? 'Cancel' : 'Back'}
            </Button>
            {step < STEPS.length ? (
              <Button onClick={next}>Next</Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => submit('active', false)} disabled={isPending}>
                  Create without syncing
                </Button>
                <LoadingButton isLoading={isPending} loadingText="Creating…" onClick={() => submit('active', true)}>
                  Create and sync now
                </LoadingButton>
              </>
            )}
          </div>
        </div>
      }
    >
      {stepError && <p className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{stepError}</p>}

      {step === 1 && (
        <div className="flex flex-col gap-5">
          {(['Content you provide', 'Connected apps'] as const).map((group) => (
            <div key={group} className="flex flex-col gap-2">
              <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{group}</h3>
              <RadioGroup value={d.type ?? ''} onValueChange={(t) => pickType(t as SourceType)} className="grid gap-2 sm:grid-cols-2">
                {SOURCE_TYPES.filter((t) => t.group === group).map((t) => {
                  const cs = connections.filter((x) => x.kind === KIND_OF[t.type]);
                  const ok = cs.some(usableConn);
                  return (
                    <label key={t.type} htmlFor={`st-${t.type}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', d.type === t.type && 'border-primary bg-primary/5')}>
                      <RadioGroupItem value={t.type} id={`st-${t.type}`} className="mt-0.5" />
                      <t.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                          {t.label}
                          {t.connected && !ok && (
                            <Badge variant="outline" className="font-normal">
                              {cs.length ? 'Reconnect' : 'Not connected'}
                            </Badge>
                          )}
                        </span>
                        <span className="block text-xs text-muted-foreground">{t.description}</span>
                      </span>
                    </label>
                  );
                })}
              </RadioGroup>
            </div>
          ))}
        </div>
      )}

      {/* A file source keeps this step mounted while hidden, so uploads in progress survive moving between steps. */}
      {meta && (step === 2 || d.type === 'file') && (
        <div className={cn('flex flex-col gap-5', step !== 2 && 'hidden')}>
          <FormField id="src-name" label="Name" error={touched && (d.name.trim().length < 2 || existingNames.some((n) => n.toLowerCase() === d.name.trim().toLowerCase())) ? errors[2] : undefined}>
            <Input id="src-name" value={d.name} onChange={(e) => set('name', e.target.value)} placeholder={d.type === 'sharepoint' ? 'e.g. Card dispute policies' : d.type === 'crawl' ? 'e.g. Public pricing pages' : 'e.g. Branch procedures'} autoFocus />
          </FormField>

          {meta.connected && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="src-conn">Connection</Label>
              <div className="flex flex-wrap gap-2">
                <Select value={d.connectionId} onValueChange={(v) => set('connectionId', v)}>
                  <SelectTrigger id="src-conn" className="min-w-56 flex-1">
                    <SelectValue placeholder={kindConns.length ? `Choose a ${meta.label} connection` : `No ${meta.label} connection yet`} />
                  </SelectTrigger>
                  <SelectContent>
                    {kindConns.map((c) => (
                      <SelectItem key={c.id} value={c.id} disabled={c.status === 'revoked'}>
                        <span className="flex items-center gap-2">
                          <SystemMark kind={c.kind} size="sm" /> {c.name}
                          {!usableConn(c) && <span className="text-xs text-muted-foreground">· {c.status === 'revoked' ? 'revoked' : 'needs reconnect'}</span>}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button type="button" variant="outline" onClick={() => onConnectNew(KIND_OF[meta.type]!)}>
                  <Plus className="size-4" /> Connect a new system
                </Button>
              </div>
              {conn && !usableConn(conn) ? (
                <Alert>
                  <Plug className="size-4" />
                  <AlertTitle>{conn.name} cannot be used until it is fixed</AlertTitle>
                  <AlertDescription className="flex flex-col items-start gap-2">
                    <p>Reconnect it in Integrations, or pick another connection.</p>
                    <ConnectionChip connection={conn} />
                  </AlertDescription>
                </Alert>
              ) : !kindConns.length ? (
                <p className="text-xs text-muted-foreground">Connections are set up once in Integrations, with their scopes, owner and expiry; every source of this type can reuse one.</p>
              ) : null}
            </div>
          )}

          {tree && !needsConnection && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Label>{meta.scopeLabel}</Label>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {d.scope.length} selected · about {plural(scopeCount, 'item')}
                </span>
              </div>
              <div className="max-h-64 overflow-y-auto rounded-md border p-2">
                <ScopeTree nodes={tree} checked={d.scope} onToggle={(nid, on) => set('scope', on ? [...d.scope, nid] : d.scope.filter((x) => x !== nid))} />
              </div>
            </div>
          )}

          {d.type === 'file' && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="src-files">Files</Label>
              <FileUpload id="src-files" purpose="knowledge_source" multiple onChange={(items) => set('files', items)} testId="source-file-upload" />
            </div>
          )}

          {d.type === 'url' && (
            <FormField id="src-urls" label="URLs, one per line">
              <Textarea id="src-urls" rows={5} value={d.urls} onChange={(e) => set('urls', e.target.value)} placeholder={'e.g. https://intranet.example.com/it/vpn-guide'} className="font-mono text-xs" />
            </FormField>
          )}

          {d.type === 'crawl' && (
            <div className="flex flex-col gap-3">
              <FormField id="src-start" label="Start URL or sitemap">
                <Input id="src-start" value={d.startUrl} onChange={(e) => set('startUrl', e.target.value)} placeholder="e.g. https://www.example.com/sitemap.xml" className="font-mono text-xs" />
              </FormField>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField id="src-depth" label="Depth (1 to 5)">
                  <Input id="src-depth" type="number" min={1} max={5} value={d.depth} onChange={(e) => set('depth', Number(e.target.value))} />
                </FormField>
                <FormField id="src-max" label="Max pages (10 to 5,000)">
                  <Input id="src-max" type="number" min={10} max={5000} value={d.maxPages} onChange={(e) => set('maxPages', Number(e.target.value))} />
                </FormField>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField id="src-inc" label="Include paths" optional>
                  <Input id="src-inc" value={d.includePaths} onChange={(e) => set('includePaths', e.target.value)} placeholder="e.g. /pricing/**, /fees/**" className="font-mono text-xs" />
                </FormField>
                <FormField id="src-exc" label="Exclude paths" optional>
                  <Input id="src-exc" value={d.excludePaths} onChange={(e) => set('excludePaths', e.target.value)} placeholder="e.g. /pricing/archive/**" className="font-mono text-xs" />
                </FormField>
              </div>
            </div>
          )}

          {d.type === 'text' && (
            <FormField id="src-text" label="Markdown">
              <Textarea id="src-text" rows={8} value={d.text} onChange={(e) => set('text', e.target.value)} placeholder={'e.g. ## Q: What are branch hours?\nMonday to Friday 9:30 to 17:00.'} className="font-mono text-xs" />
            </FormField>
          )}

          {!needsConnection && d.type !== 'text' && (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" size="sm" onClick={runPreview} disabled={previewing}>
                  {previewing && <Loader2 className="size-3.5 animate-spin" />} Preview what it fetches
                </Button>
                {preview && <span className={cn('text-xs', preview.ok ? 'text-emerald-600' : 'text-destructive')}>{preview.message}</span>}
              </div>
              {preview?.ok && preview.rows.length > 0 && (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Title</TableHead>
                        <TableHead>Path</TableHead>
                        <TableHead className="text-right">Size</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {preview.rows.slice(0, 6).map((p, i) => (
                        <TableRow key={i}>
                          <TableCell className="max-w-52 truncate">{p.title}</TableCell>
                          <TableCell className="max-w-52 truncate font-mono text-xs text-muted-foreground">{p.path}</TableCell>
                          <TableCell className="text-right tabular-nums">{bytes(p.size)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {preview.rows.length > 6 && <p className="border-t px-3 py-1.5 text-xs text-muted-foreground">and {count(preview.rows.length - 6)} more</p>}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-5">
          <IngestForm idPrefix="add" ingest={d.ingest} parsing={d.parsing} onIngest={(v) => set('ingest', v)} onParsing={(v) => set('parsing', v)} />
          <SplitPreviewPanel idPrefix="add" samples={samples} samplesLoading={samplesLoading} ingest={d.ingest} parsing={d.parsing} mapping={d.mapping} onPreview={onPreviewSplit} />
        </div>
      )}

      {step === 4 && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label>Include and exclude rules</Label>
            <p className="text-xs text-muted-foreground">Any include rule admits an item; exclude rules win.</p>
            {d.rules.map(ruleRow)}
            <Button variant="outline" size="sm" className="w-fit" onClick={() => set('rules', [...d.rules, { id: `r${Date.now()}`, kind: 'exclude', field: 'path', value: '' }])}>
              <Plus className="size-3.5" /> Add rule
            </Button>
          </div>
          <div className="flex flex-col gap-2">
            <Label>Attach to knowledge bases</Label>
            <p className="text-xs text-muted-foreground">Optional. Each one indexes the items on its next refresh, and holds any item missing a key it requires.</p>
            <div className="flex flex-wrap gap-2">
              {knowledgeBases.map((k) => (
                <label key={k.id} htmlFor={`src-kb-${k.id}`} className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1 text-xs', d.kbIds.includes(k.id) && 'border-primary bg-primary/5')}>
                  <Checkbox id={`src-kb-${k.id}`} checked={d.kbIds.includes(k.id)} onCheckedChange={(v) => set('kbIds', v ? [...d.kbIds, k.id] : d.kbIds.filter((x) => x !== k.id))} className="size-3.5" /> {k.name}
                </label>
              ))}
            </div>
            {held && held.byKb.length > 0 && (
              <ul className="flex flex-col gap-1 rounded-md border bg-muted/40 px-3 py-2 text-xs" data-testid="required-metadata">
                {held.byKb.map((k) => (
                  <li key={k.kbId} className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium">{k.kbName} requires</span>
                    {k.required.map((key) => (
                      <Badge key={key} variant="outline" className={cn('font-mono text-[11px] font-normal', k.missing.includes(key) && 'border-amber-300 text-amber-700 dark:border-amber-800 dark:text-amber-400')}>
                        {key}
                      </Badge>
                    ))}
                    {k.missing.length > 0 && <span className="text-muted-foreground">· map {k.missing.join(', ')} below or items are held</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Label>Metadata</Label>
            <p className="text-xs text-muted-foreground">Each key comes from a field at the source, a fixed value such as locale = en, or a model reading the document at ingest.</p>
            <MetadataMappingEditor value={d.mapping} onChange={(v) => set('mapping', v)} model={d.ingest.model} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="src-tags" label="Tags on every item" optional>
              <TagInput id="src-tags" value={d.tags} onChange={(v) => set('tags', v)} suggestions={['policy', 'cards', 'lending', 'pricing', 'faq', 'procedure']} placeholder="e.g. policy" />
            </FormField>
            <FormField id="src-title" label="Title from">
              <Select value={d.titleFrom} onValueChange={(v) => set('titleFrom', v as Draft['titleFrom'])}>
                <SelectTrigger id="src-title" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="source">Title at the source</SelectItem>
                  <SelectItem value="heading">First heading</SelectItem>
                  <SelectItem value="filename">Filename</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="src-collection" label="Collection" optional hint="The department boundary a knowledge base can be limited to.">
              <Input id="src-collection" list="src-collections" value={d.collection} onChange={(e) => set('collection', e.target.value)} placeholder="e.g. Lending" />
              <datalist id="src-collections">
                {collections.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </FormField>
            <FormField id="src-sens" label="Sensitivity">
              <Select value={d.sensitivity} onValueChange={(v) => set('sensitivity', v as Sensitivity)}>
                <SelectTrigger id="src-sens" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="internal">Internal</SelectItem>
                  <SelectItem value="confidential">Confidential</SelectItem>
                  <SelectItem value="restricted">Restricted, never sent to a model unredacted</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </div>
        </div>
      )}

      {step === 5 && meta && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label>Who can see its items</Label>
            <RadioGroup value={d.permissions} onValueChange={(v) => set('permissions', v as Draft['permissions'])} className="grid gap-2">
              {meta.supportsInherit && (
                <label htmlFor="perm-inherit" className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', d.permissions === 'inherit' && 'border-primary bg-primary/5')}>
                  <RadioGroupItem value="inherit" id="perm-inherit" className="mt-0.5" />
                  <span>
                    <span className="block text-sm font-medium">Inherit from {meta.short}</span>
                    <span className="block text-xs text-muted-foreground">Each item keeps its own permissions, so a person sees what they can open at the source.</span>
                  </span>
                </label>
              )}
              <label htmlFor="perm-ws" className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', d.permissions === 'workspace' && 'border-primary bg-primary/5')}>
                <RadioGroupItem value="workspace" id="perm-ws" className="mt-0.5" />
                <span>
                  <span className="block text-sm font-medium">Workspace-wide</span>
                  <span className="block text-xs text-muted-foreground">Every agent and member that can query a knowledge base sees these items.</span>
                </span>
              </label>
              <label htmlFor="perm-sel" className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', d.permissions === 'selected' && 'border-primary bg-primary/5')}>
                <RadioGroupItem value="selected" id="perm-sel" className="mt-0.5" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">Selected members and groups</span>
                  {d.permissions === 'selected' && (
                    <span className="mt-2 block">
                      <TagInput value={d.principals} onChange={(v) => set('principals', v)} suggestions={['group:Card Services', 'group:Lending', 'group:Compliance', 'group:Fraud']} placeholder="e.g. group:Lending" />
                    </span>
                  )}
                </span>
              </label>
            </RadioGroup>
          </div>
          <div className="flex flex-col gap-2">
            <Label>Refresh schedule</Label>
            <RadioGroup value={d.schedule.kind} onValueChange={(v) => set('schedule', scheduleFor(v as Schedule['kind']))} className="flex flex-wrap gap-2">
              {(['manual', 'daily', 'weekly', 'monthly', 'webhook'] as const).map((k) => (
                <label key={k} htmlFor={`sch-${k}`} className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm', d.schedule.kind === k && 'border-primary bg-primary/5', k === 'webhook' && !meta.supportsWebhook && 'cursor-not-allowed opacity-50')}>
                  <RadioGroupItem value={k} id={`sch-${k}`} disabled={k === 'webhook' && !meta.supportsWebhook} /> {k === 'webhook' ? 'When the source changes' : k[0].toUpperCase() + k.slice(1)}
                </label>
              ))}
            </RadioGroup>
            {d.schedule.kind === 'daily' && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">At</span>
                <Input type="time" className="h-8 w-32" value={d.schedule.time} onChange={(e) => set('schedule', { kind: 'daily', time: e.target.value })} aria-label="Time" />
              </div>
            )}
            {d.schedule.kind === 'weekly' &&
              (() => {
                const w = d.schedule;
                return (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Select value={w.day} onValueChange={(v) => set('schedule', { ...w, day: v })}>
                      <SelectTrigger className="h-8 w-28" aria-label="Day">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((x) => (
                          <SelectItem key={x} value={x}>
                            {x}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Input type="time" className="h-8 w-32" value={w.time} onChange={(e) => set('schedule', { ...w, time: e.target.value })} aria-label="Time" />
                  </div>
                );
              })()}
            {d.schedule.kind === 'monthly' &&
              (() => {
                const m = d.schedule;
                return (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted-foreground">Day</span>
                    <Input type="number" min={1} max={28} className="h-8 w-20" value={m.day} onChange={(e) => set('schedule', { ...m, day: Math.min(28, Math.max(1, Number(e.target.value) || 1)) })} aria-label="Day of month" />
                    <Input type="time" className="h-8 w-32" value={m.time} onChange={(e) => set('schedule', { ...m, time: e.target.value })} aria-label="Time" />
                  </div>
                );
              })()}
            {d.schedule.kind === 'webhook' && (
              <div className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                <Label htmlFor="safety" className="font-normal">
                  Also run daily as a safety net
                </Label>
                <Switch id="safety" checked={d.schedule.safetyNetDaily} onCheckedChange={(v) => set('schedule', { kind: 'webhook', safetyNetDaily: v })} />
              </div>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField id="src-deleted" label="When an item is deleted at the source">
              <Select value={d.deletedAtSource} onValueChange={(v) => set('deletedAtSource', v as Draft['deletedAtSource'])}>
                <SelectTrigger id="src-deleted" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="remove">Remove it from the index</SelectItem>
                  <SelectItem value="keep_stale">Keep it and mark it stale</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="src-stale" label="Stale after (days)" hint="Past this, items are flagged for their owner to review.">
              <Input id="src-stale" type="number" min={1} value={d.staleAfter} onChange={(e) => set('staleAfter', Math.max(1, Number(e.target.value) || 1))} />
            </FormField>
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
            <Label htmlFor="src-notify" className="font-normal">
              Notify the owner when a sync fails
            </Label>
            <Switch id="src-notify" checked={d.notify} onCheckedChange={(v) => set('notify', v)} />
          </div>
        </div>
      )}

      {step === 6 && meta && (
        <div className="flex flex-col gap-4">
          {submitError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{submitError}</p>}
          {held && heldTotal.length > 0 && (
            <Alert data-testid="held-warning">
              <Info className="size-4" />
              <AlertTitle>Some items would be held</AlertTitle>
              <AlertDescription className="flex flex-col items-start gap-2">
                <ul className="list-disc pl-4">
                  {heldTotal.map((k) => (
                    <li key={k.kbId}>
                      {k.kbName}: {k.held} of {plural(held.items, 'previewed item')} missing {k.missing.join(', ')}
                    </li>
                  ))}
                </ul>
                <p>Held items are stored but not searched until the missing keys are added.</p>
                <Button size="sm" variant="outline" onClick={() => setStep(4)}>
                  Map the missing keys
                </Button>
              </AlertDescription>
            </Alert>
          )}
          {reviewSections.map(([title, target, rows]) => (
            <div key={title} className="rounded-lg border">
              <div className="flex items-center justify-between border-b px-3 py-2">
                <span className="text-sm font-medium">{title}</span>
                <Button variant="ghost" size="sm" onClick={() => setStep(target)}>
                  <Pencil className="size-3.5" /> Edit
                </Button>
              </div>
              <div className="px-3">
                <KeyValues rows={rows} />
              </div>
            </div>
          ))}
        </div>
      )}
    </DialogShell>
  );
}
