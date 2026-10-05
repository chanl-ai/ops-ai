'use client';

import * as React from 'react';
import {
  addEdge,
  Background,
  BackgroundVariant,
  type Connection,
  type Edge,
  MiniMap,
  type Node,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AlertTriangle, CheckCircle2, Play, Trash2, UserCheck } from 'lucide-react';
import { toast } from 'sonner';

import { LiveBadge } from '@/components/status-badges';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { type GraphIssue, graphIssues } from './graph-checks';
import { diffGraphs } from './graph-diff';
import { EmailConfigContext } from './email-config-context';
import { RequestPublishDialog } from './request-publish-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { useSidebar } from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import type { Review, Workflow, ValidationRun, WorkflowDetail, WorkflowGraph } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

import { CanvasControls } from './canvas-controls';
import { NodePalette } from './node-palette';
import { CAT_COLORS, DND_MIME, GROUP_LABEL, type OptionSource, paletteToNode, resolveKind, type StepData } from './node-types';
import { nodeTypes } from './workflow-nodes';

type FlowNode = Node<StepData>;

const TYPE_LABEL: Record<string, string> = { trigger: 'Trigger', step: 'Step', router: 'Classify and route', branch: 'Branch', end: 'End', review: 'Approval gate' };
const DURATIONS = ['5 min', '15 min', '1 h', '4 h', '1 day', '3 days'];
const SCHEDULES = ['Every hour', 'Daily at 08:00', 'Weekdays at 08:00', 'First business day of the quarter'];


function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs">{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Keeps the typed text while editing and only splits it into branches on blur or Enter, so commas survive typing. */
function BranchesInput({ value, onCommit }: { value: string[]; onCommit: (v: string[]) => void }) {
  const [text, setText] = React.useState(value.join(', '));
  React.useEffect(() => {
    setText(value.join(', '));
  }, [value]);
  const commit = () => {
    const next = [...new Set(text.split(',').map((x) => x.trim()).filter(Boolean))];
    if (next.length && next.join('|') !== value.join('|')) onCommit(next);
    else setText(value.join(', '));
  };
  return (
    <Input
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          commit();
        }
      }}
      className="h-8"
    />
  );
}

function Inspector({
  workflow,
  reviewerGroups,
  slaOptions,
  agents,
  toolOptions,
  lookupOptions,
  issues,
  nodes,
  selected,
  onChange,
  onDelete,
  onSelect,
}: {
  workflow: Workflow;
  reviewerGroups: string[];
  slaOptions: string[];
  agents: { slug: string; name: string }[];
  toolOptions: { name: string; access: string }[];
  lookupOptions: LookupOptions;
  issues: GraphIssue[];
  nodes: FlowNode[];
  selected: FlowNode | null;
  onChange: (patch: Partial<StepData>) => void;
  onDelete: () => void;
  onSelect: (id: string) => void;
}) {
  if (!selected) {
    const gates = nodes.filter((n) => n.type === 'review');
    const rate = workflow.runs24h ? Math.round((workflow.reviewed24h / workflow.runs24h) * 100) : 0;
    return (
      <div className="flex flex-col gap-5 p-4">
        <div>
          <p className="text-xs text-muted-foreground">Workflow</p>
          <p className="font-semibold">{workflow.name}</p>
          <p className="text-sm text-muted-foreground">Starts on: {workflow.trigger}</p>
        </div>
        <div className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border bg-border text-center">
          {[
            ['Runs · 24h', workflow.runs24h.toLocaleString()],
            ['To review', workflow.reviewed24h.toLocaleString()],
            ['Review rate', `${rate}%`],
          ].map(([l, v]) => (
            <div key={l} className="bg-card px-2 py-2.5">
              <div className="text-base font-semibold tabular-nums">{v}</div>
              <div className="text-[10px] text-muted-foreground">{l}</div>
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Human review gates · {gates.length}</p>
          {gates.map((g) => (
            <button
              key={g.id}
              onClick={() => onSelect(g.id)}
              className="flex items-start gap-2.5 rounded-lg border border-dashed border-amber-500/50 p-2.5 text-left hover:bg-amber-500/5"
            >
              <UserCheck className="mt-0.5 size-4 shrink-0 text-amber-600" />
              <div className="min-w-0">
                <div className="text-sm font-medium">{g.data.label}</div>
                <div className="text-xs text-muted-foreground">
                  {g.data.reviewers} · {g.data.sla}
                </div>
              </div>
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-2" data-testid="graph-checks">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Checks · {issues.length ? `${issues.length} to fix` : 'all clear'}</p>
          {issues.length === 0 ? (
            <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="size-4" /> Every step is wired and configured.
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {issues.map((i, k) => (
                <li key={k}>
                  <button
                    type="button"
                    disabled={!i.nodeId}
                    onClick={() => i.nodeId && onSelect(i.nodeId)}
                    className="flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-sm hover:bg-muted disabled:hover:bg-transparent"
                  >
                    <AlertTriangle className={cn('mt-0.5 size-3.5 shrink-0', i.severity === 'error' ? 'text-red-600' : 'text-amber-600')} />
                    {i.message}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  const d = selected.data;
  const colors = CAT_COLORS[d.category] ?? CAT_COLORS.ai;
  const kind = resolveKind(selected);
  const options: Record<OptionSource, { value: string; label: string }[]> = {
    agents: agents.map((a) => ({ value: a.slug, label: a.name })),
    tools: toolOptions.map((t) => ({ value: t.name, label: t.access === 'money_movement' ? `${t.name} · moves money` : t.name })),
    collections: lookupOptions.collections.map((c) => ({ value: c, label: c })),
    workflows: lookupOptions.workflows.filter((w) => w.id !== workflow.id).map((w) => ({ value: w.name, label: w.name })),
    owners: lookupOptions.owners.map((o) => ({ value: o, label: o })),
    reviewerGroups: reviewerGroups.map((g) => ({ value: g, label: g })),
    sla: slaOptions.map((o) => ({ value: o, label: o })),
    durations: DURATIONS.map((o) => ({ value: o, label: o })),
    schedules: SCHEDULES.map((o) => ({ value: o, label: o })),
  };
  const fields = kind?.fields ?? (selected.type === 'review' || selected.type === 'end' ? [] : [{ key: 'description', label: 'Description', input: 'text' as const }]);
  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-2">
        <span className={cn('rounded-md px-2 py-0.5 text-[11px] font-medium', colors.bg, colors.text)}>{GROUP_LABEL[d.category] ?? 'Step'}</span>
        <span className="text-xs text-muted-foreground">{kind?.label ?? TYPE_LABEL[selected.type ?? 'step']}</span>
        <Button variant="ghost" size="icon" className="ml-auto size-7" onClick={onDelete} aria-label="Delete step">
          <Trash2 className="size-3.5" />
        </Button>
      </div>
      <Field label="Name">
        <Input value={d.label} onChange={(e) => onChange({ label: e.target.value })} className="h-8" />
      </Field>
      {fields.map((f) => {
        const value = String(d[f.key] ?? '');
        const missing = f.required && !value;
        if (f.input === 'select') {
          const opts = options[f.options!];
          return (
            <Field key={f.key} label={f.label} hint={f.hint}>
              <Select
                value={opts.some((o) => o.value === value) ? value : ''}
                onValueChange={(v) => onChange(f.key === 'agentSlug' ? { agentSlug: v, badge: `agent · ${v}` } : { [f.key]: v })}
              >
                <SelectTrigger className={cn('h-8 w-full', f.mono && 'font-mono text-xs')} aria-invalid={missing}>
                  <SelectValue placeholder={`Choose ${f.label.toLowerCase()}`} />
                </SelectTrigger>
                <SelectContent>
                  {opts.map((o) => (
                    <SelectItem key={o.value} value={o.value} className={cn(f.mono && 'font-mono text-xs')}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          );
        }
        if (f.input === 'branches') {
          return (
            <Field key={`${selected.id}-${f.key}`} label={f.label} hint="Comma separated. Each becomes an output to connect.">
              <BranchesInput value={d.branches ?? []} onCommit={(branches) => onChange({ branches })} />
            </Field>
          );
        }
        if (f.input === 'textarea') {
          return (
            <Field key={f.key} label={f.label} hint={f.hint}>
              <Textarea value={value} placeholder={f.placeholder} onChange={(e) => onChange({ [f.key]: e.target.value })} className={cn('min-h-20', f.mono && 'font-mono text-xs')} aria-invalid={missing} />
            </Field>
          );
        }
        return (
          <Field key={f.key} label={f.label} hint={f.hint}>
            <Input value={value} placeholder={f.placeholder} onChange={(e) => onChange({ [f.key]: e.target.value })} className={cn('h-8', f.mono && 'font-mono text-xs')} aria-invalid={missing} />
          </Field>
        );
      })}
      {selected.type === 'review' && (
        <>
          <Separator />
          <Field label="Pause the run when" hint="Runs that do not match continue without a person.">
            <Textarea value={d.condition ?? ''} onChange={(e) => onChange({ condition: e.target.value })} className="min-h-16 font-mono text-xs" />
          </Field>
          <Field label="Reviewer group">
            <Select value={d.reviewers} onValueChange={(v) => onChange({ reviewers: v })}>
              <SelectTrigger className="h-8 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {reviewerGroups.map((g) => (
                  <SelectItem key={g} value={g}>
                    {g}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Decision SLA">
            <Select value={d.sla} onValueChange={(v) => onChange({ sla: v })}>
              <SelectTrigger className="h-8 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {slaOptions.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <label className="flex items-start gap-2.5 rounded-lg border p-3">
            <Checkbox checked={!!d.fourEyes} onCheckedChange={(v) => onChange({ fourEyes: !!v })} className="mt-0.5" />
            <span>
              <span className="block text-sm font-medium">Require two approvers</span>
              <span className="block text-xs text-muted-foreground">Both from the reviewer group; the proposer cannot approve.</span>
            </span>
          </label>
          <div className="rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">
            <p className="mb-1.5 font-medium text-foreground">Outputs</p>
            <p><span className="font-medium text-emerald-600">Approved</span> continues with the agent&apos;s proposal.</p>
            <p><span className="font-medium text-red-600">Rejected</span> returns the reviewer&apos;s reason to the agent.</p>
            <p><span className="font-medium">SLA lapsed</span> follows the dashed path.</p>
          </div>
        </>
      )}
    </div>
  );
}

export interface LookupOptions {
  collections: string[];
  owners: string[];
  workflows: { id: string; name: string }[];
}

export interface WorkflowEditorProps {
  workflow: WorkflowDetail;
  reviewerGroups: string[];
  slaOptions: string[];
  /** Names of tools that move money; publishing warns when one is reachable without a review gate. */
  moneyTools: string[];
  agents: { slug: string; name: string }[];
  toolOptions: { name: string; access: string }[];
  lookupOptions: LookupOptions;
  onValidate: (graph: WorkflowGraph) => Promise<ValidationRun>;
  onRequestPublish: (graph: WorkflowGraph, note: string, validationRunId: string | undefined, checksFailing: number) => Promise<Review>;
  isRequesting: boolean;
  /** Persists the canvas draft (null discards it). Called as the user edits. */
  onSaveDraft: (graph: WorkflowGraph | null) => Promise<unknown>;
  /** Tab strip rendered in the top bar. */
  tabs: React.ReactNode;
  /** Header actions beside Publish (status menu). */
  extraActions?: React.ReactNode;
  showCanvas: boolean;
  /** Content for the non-canvas tabs; the canvas state stays alive while they show. */
  children?: React.ReactNode;
}

/** What autosave compares, so an unchanged graph is never re-sent. */
const snapshot = (g: Pick<WorkflowGraph, 'nodes' | 'edges' | 'emailConfig'>) => JSON.stringify({ nodes: g.nodes, edges: g.edges, emailConfig: g.emailConfig });

function EditorInner({ workflow, reviewerGroups, slaOptions, moneyTools, agents, toolOptions, lookupOptions, onValidate, onRequestPublish, isRequesting, onSaveDraft, tabs, extraActions, showCanvas, children }: WorkflowEditorProps) {
  // Open on the saved draft when there is one, so edits survive leaving the page.
  const start = workflow.draft?.graph ?? workflow.graph;
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(start.nodes as FlowNode[]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(start.edges as Edge[]);
  const [publishOpen, setPublishOpen] = React.useState(false);
  const [validation, setValidation] = React.useState<ValidationRun | undefined>();
  const [validating, setValidating] = React.useState(false);
  const [validationError, setValidationError] = React.useState<string | null>(null);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [dirty, setDirty] = React.useState(!!workflow.draft);
  const [emailConfig, setEmailConfigState] = React.useState(start.emailConfig);
  const setEmailConfig = React.useCallback((c: NonNullable<WorkflowGraph['emailConfig']>) => {
    setEmailConfigState(c);
    setDirty(true);
  }, []);
  const emailCtx = React.useMemo(() => ({ config: emailConfig, setConfig: setEmailConfig }), [emailConfig, setEmailConfig]);
  const [saveState, setSaveState] = React.useState<'saved' | 'saving' | 'error'>('saved');
  const [running, setRunning] = React.useState(false);
  const { screenToFlowPosition, fitView, setViewport, getNodesBounds } = useReactFlow();
  const canvasRef = React.useRef<HTMLDivElement>(null);
  const { setOpen: setSidebarOpen } = useSidebar();
  // The canvas needs the width; the app nav collapses to icons while editing.
  React.useEffect(() => {
    if (!showCanvas) return;
    setSidebarOpen(false);
    // Anchor the graph at its trigger (left edge) at a readable zoom; wide graphs scroll right instead of shrinking illegibly.
    const t = setTimeout(() => {
      const el = canvasRef.current;
      if (!el || !nodes.length) return;
      const b = getNodesBounds(nodes);
      const zoom = Math.min(1, Math.max(0.85, (el.clientWidth - 48) / b.width));
      setViewport({ x: 24 - b.x * zoom, y: (el.clientHeight - b.height * zoom) / 2 - b.y * zoom, zoom });
    }, 320);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setSidebarOpen, showCanvas]);
  const issues = React.useMemo(
    () => graphIssues({ nodes: nodes as WorkflowGraph['nodes'], edges: edges as WorkflowGraph['edges'] }, { agentSlugs: agents.map((a) => a.slug), toolNames: toolOptions.map((t) => t.name), moneyTools }),
    [nodes, edges, agents, toolOptions, moneyTools],
  );
  const counter = React.useRef(0);

  const selected = nodes.find((n) => n.id === selectedId) ?? null;

  const addNode = React.useCallback(
    (paletteId: string, position?: { x: number; y: number }) => {
      const spec = paletteToNode(paletteId);
      if (!spec) return;
      const id = `${spec.type}_${++counter.current}`;
      const start = position ?? screenToFlowPosition({ x: window.innerWidth / 2 - 100, y: window.innerHeight / 2 });
      // Step down until the new node no longer sits on an existing one, so a click-added node is always visible.
      const pos = { ...start };
      for (let i = 0; i < 12 && nodes.some((n) => Math.abs(n.position.x - pos.x) < 200 && Math.abs(n.position.y - pos.y) < 90); i++) pos.y += 110;
      setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), { id, type: spec.type, position: pos, data: spec.data, selected: true }]);
      setSelectedId(id);
      setDirty(true);
    },
    [screenToFlowPosition, setNodes, nodes],
  );

  const onConnect = React.useCallback(
    (c: Connection) => {
      const label = c.sourceHandle === 'approved' ? 'Approved' : c.sourceHandle === 'rejected' ? 'Rejected' : c.sourceHandle === 'timeout' ? 'SLA lapsed' : undefined;
      setEdges((es) => addEdge({ ...c, type: 'smoothstep', label }, es));
      setDirty(true);
    },
    [setEdges],
  );

  const patchSelected = (patch: Partial<StepData>) => {
    setNodes((ns) => ns.map((n) => (n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n)));
    setDirty(true);
  };

  const deleteSelected = () => {
    setNodes((ns) => ns.filter((n) => n.id !== selectedId));
    setEdges((es) => es.filter((e) => e.source !== selectedId && e.target !== selectedId));
    setSelectedId(null);
    setDirty(true);
  };

  const draftGraph = (): WorkflowGraph => ({
    workflowId: workflow.id,
    nodes: nodes.map(({ id, type, position, data }) => ({ id, type: type ?? 'step', position, data: { ...data, status: undefined } })),
    edges: edges.map(({ id, source, target, sourceHandle, label, type }) => ({ id, source, target, sourceHandle, label: typeof label === 'string' ? label : undefined, type })),
    ...(emailConfig ? { emailConfig } : {}),
  });
  const runValidation = () => {
    setValidating(true);
    setValidationError(null);
    onValidate(draftGraph())
      .then(setValidation)
      .catch((e: Error) => setValidationError(e.message))
      .finally(() => setValidating(false));
  };

  // Autosave: debounce edits into the draft; flush immediately when the editor unmounts (tab switch, navigation).
  const pendingSave = React.useRef<{ timer: ReturnType<typeof setTimeout> | null; json: string }>({ timer: null, json: snapshot(start) });
  const flush = React.useCallback(
    (graph: WorkflowGraph) => {
      const json = snapshot(graph);
      if (json === pendingSave.current.json) return;
      pendingSave.current.json = json;
      setSaveState('saving');
      onSaveDraft(graph)
        .then(() => setSaveState('saved'))
        .catch(() => setSaveState('error'));
    },
    [onSaveDraft],
  );
  const latest = React.useRef<() => WorkflowGraph>(() => draftGraph());
  latest.current = draftGraph;
  React.useEffect(() => {
    if (!dirty) return;
    const p = pendingSave.current;
    if (p.timer) clearTimeout(p.timer);
    p.timer = setTimeout(() => {
      p.timer = null;
      flush(latest.current());
    }, 700);
  }, [nodes, edges, emailConfig, dirty, flush]);
  React.useEffect(
    () => () => {
      const p = pendingSave.current;
      if (p.timer) {
        clearTimeout(p.timer);
        flush(latest.current());
      }
    },
    [flush],
  );
  React.useEffect(() => {
    if (saveState !== 'saving') return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [saveState]);
  const [discardOpen, setDiscardOpen] = React.useState(false);

  const testRun = () => {
    const start = nodes.find((n) => n.type === 'trigger');
    if (!start) return toast.error('Add a trigger before running a test');
    const path: string[] = [];
    let cur: FlowNode | undefined = start;
    while (cur && !path.includes(cur.id)) {
      path.push(cur.id);
      if (cur.type === 'review') break;
      const id: string = cur.id;
      const next = edges.find((e) => e.source === id && (e.sourceHandle == null || ['mid', 'Gate', 'approved'].includes(e.sourceHandle))) ?? edges.find((e) => e.source === id);
      cur = next ? nodes.find((n) => n.id === next.target) : undefined;
    }
    setRunning(true);
    setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, status: undefined } })));
    path.forEach((id, i) => {
      setTimeout(() => {
        setNodes((ns) =>
          ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, status: 'active' } } : path.slice(0, i).includes(n.id) ? { ...n, data: { ...n.data, status: 'success' } } : n)),
        );
        if (i === path.length - 1) {
          setRunning(false);
          const last = nodes.find((n) => n.id === id);
          if (last?.type === 'review') {
            toast('Test run paused for review', { description: `In production this run would wait for ${last.data.reviewers} (${last.data.sla} SLA).` });
          } else {
            toast.success('Test run completed');
          }
        }
      }, 450 * (i + 1));
    });
  };

  return (
    <EmailConfigContext.Provider value={emailCtx}>
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2.5 lg:px-6">
        <Link href="/workflows" className="flex size-8 shrink-0 items-center justify-center rounded-md border text-muted-foreground hover:text-foreground" aria-label="Back to workflows">
          <ArrowLeft className="size-4" />
        </Link>
        <div className="min-w-0 max-w-72">
          <h2 className="truncate font-semibold" data-testid="page-title">{workflow.name}</h2>
          <p className="truncate text-xs text-muted-foreground">Starts when: {workflow.trigger}</p>
        </div>
        <LiveBadge status={workflow.status} />
        <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums" data-testid="editor-version">
          v{workflow.version}
          {dirty && (saveState === 'saving' ? ' · saving draft…' : saveState === 'error' ? ' · draft not saved' : ' · draft saved')}
        </span>
        <div className="order-last w-full md:order-none md:ml-4 md:w-auto">{tabs}</div>
        <div className="ml-auto flex items-center gap-2">
          {dirty && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDiscardOpen(true)}
            >
              Discard draft
            </Button>
          )}
          {showCanvas && (
            <Button variant="outline" size="sm" onClick={testRun} disabled={running}>
              <Play className="size-3.5" /> {running ? 'Running…' : 'Test run'}
            </Button>
          )}
          {extraActions}
          {workflow.pendingPublish ? (
            <Button size="sm" variant="outline" className="border-amber-500/50 text-amber-800 dark:text-amber-300" asChild>
              <Link href={`/reviews?review=${workflow.pendingPublish.reviewId}`}>Awaiting approval · v{workflow.pendingPublish.toVersion}</Link>
            </Button>
          ) : (
            <Button
              size="sm"
              disabled={!dirty && workflow.status !== 'draft'}
              title={!dirty && workflow.status !== 'draft' ? 'No changes since the live version' : undefined}
              onClick={() => {
                setPublishOpen(true);
                runValidation();
              }}
            >
              Publish…
            </Button>
          )}
        </div>
      </div>
      {workflow.pendingPublish && showCanvas && (
        <div className="flex flex-wrap items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-900 lg:px-6 dark:text-amber-200" role="status" data-testid="pending-publish-banner">
          v{workflow.pendingPublish.toVersion} is waiting for approval from another publisher. The canvas shows your draft; changes you make now are saved but are not part of that request.
          <Link href={`/reviews?review=${workflow.pendingPublish.reviewId}`} className="ml-auto font-medium underline underline-offset-2">
            Open request
          </Link>
        </div>
      )}
      {!showCanvas ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 lg:px-6">{children}</div>
      ) : (
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[260px] shrink-0 border-r md:block">
          <NodePalette embedded onAdd={(id) => addNode(id)} />
        </aside>
        <div
          ref={canvasRef}
          className="relative min-w-0 flex-1"
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
          }}
          onDrop={(e) => {
            e.preventDefault();
            const id = e.dataTransfer.getData(DND_MIME);
            if (id) addNode(id, screenToFlowPosition({ x: e.clientX, y: e.clientY }));
          }}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={(c) => {
              onNodesChange(c);
              if (c.some((x) => x.type === 'position' || x.type === 'remove')) setDirty(true);
            }}
            onEdgesChange={(c) => {
              onEdgesChange(c);
              if (c.some((x) => x.type === 'remove')) setDirty(true);
            }}
            onConnect={onConnect}
            onSelectionChange={({ nodes: sel }) => setSelectedId(sel[0]?.id ?? null)}
            nodeTypes={nodeTypes}
            defaultEdgeOptions={{ type: 'smoothstep' }}
            minZoom={0.2}
            maxZoom={1.5}
            proOptions={{ hideAttribution: true }}
            className="bg-muted/30"
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
            <Panel position="top-right">
              <CanvasControls />
            </Panel>
            <MiniMap pannable zoomable className="!bottom-2 !right-2 max-xl:!hidden" nodeStrokeWidth={2} nodeColor={(n) => (n.type === 'review' ? '#f59e0b' : n.type === 'trigger' ? '#8b5cf6' : '#94a3b8')} />
          </ReactFlow>
        </div>
        <aside className="hidden w-80 shrink-0 overflow-y-auto border-l bg-card lg:block">
          <Inspector
            workflow={workflow}
            reviewerGroups={reviewerGroups}
            slaOptions={slaOptions}
            agents={agents}
            toolOptions={toolOptions}
            lookupOptions={lookupOptions}
            issues={issues}
            nodes={nodes}
            selected={selected}
            onChange={patchSelected}
            onDelete={deleteSelected}
            onSelect={(id) => {
              setNodes((ns) => ns.map((n) => ({ ...n, selected: n.id === id })));
              setSelectedId(id);
              fitView({ nodes: [{ id }], duration: 300, maxZoom: 1.1 });
            }}
          />
        </aside>
      </div>
      )}

      <DialogShell
        open={discardOpen}
        onOpenChange={setDiscardOpen}
        size="sm"
        title="Discard the draft?"
        description={`The canvas goes back to live v${workflow.version}. ${workflow.pendingPublish ? `The request for v${workflow.pendingPublish.toVersion} keeps its own copy and stays in Reviews.` : 'This cannot be undone.'}`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setDiscardOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                const p = pendingSave.current;
                if (p.timer) clearTimeout(p.timer);
                p.timer = null;
                p.json = snapshot(workflow.graph);
                setNodes(workflow.graph.nodes as FlowNode[]);
                setEmailConfigState(workflow.graph.emailConfig);
                setEdges(workflow.graph.edges as Edge[]);
                setSelectedId(null);
                setDirty(false);
                setDiscardOpen(false);
                try {
                  await onSaveDraft(null);
                  toast.success('Draft discarded');
                } catch (e) {
                  toast.error('Couldn’t discard the draft', { description: (e as Error).message });
                }
              }}
            >
              Discard draft
            </Button>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">Every unpublished change on the canvas is removed.</p>
      </DialogShell>

      <RequestPublishDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        nextVersion={workflow.status === 'draft' ? workflow.version : workflow.version + 1}
        firstPublish={workflow.status === 'draft'}
        diff={diffGraphs(workflow.graph, { nodes: nodes as WorkflowGraph['nodes'], edges: edges as WorkflowGraph['edges'], emailConfig })}
        issues={issues}
        validation={validation}
        validating={validating}
        validationError={validationError}
        onRevalidate={runValidation}
        isPending={isRequesting}
        onRequest={async (note) => {
          const review = await onRequestPublish(draftGraph(), note, validation?.id, issues.length);
          toast.success(`Sent ${review.id} for approval`, { description: 'Another publisher approves it in Reviews. Your draft stays here until then.' });
        }}
      />
    </div>
    </EmailConfigContext.Provider>
  );
}

export function WorkflowEditor(props: WorkflowEditorProps) {
  return (
    <ReactFlowProvider>
      <EditorInner {...props} />
    </ReactFlowProvider>
  );
}
