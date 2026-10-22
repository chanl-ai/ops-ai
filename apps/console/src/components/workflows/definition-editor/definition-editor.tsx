'use client';

import * as React from 'react';
import {
  Background,
  BackgroundVariant,
  type Connection,
  type Edge,
  MiniMap,
  type OnDelete,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AlertTriangle, CheckCircle2, Keyboard, Play, Save } from 'lucide-react';
import { toast } from 'sonner';

import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { ApiError } from '@/lib/api/contract';
import type { DefinitionCheck, DefinitionPublished, DefinitionValidation, EngineDefinition, EngineNode, EngineNodeType } from '@/lib/types/engine';

import { CanvasControls } from '../canvas-controls';
import { MIN_ZOOM, readableFit, wholeFit } from './canvas-view';
import { ChecksPanel } from './checks-panel';
import { type DefinitionFlowNode, definitionNodeTypes } from './definition-node';
import { connectionId, inPorts, indexTypes, outPorts, repeatsOver, typeKey, uniqueNodeId, withPositions } from './graph';
import { LifecycleActions, type Lifecycle } from './lifecycle';
import type { StepRef, StepRefs } from './node-form';
import { PublishDefinitionDialog } from './publish-dialog';
import { type RunMode, StartDefinitionRunDialog } from '@/components/workflows/start-run-dialog';
import { StepList } from './step-list';
import { StepSheet } from './step-sheet';

export interface DefinitionEditorProps {
  definition: EngineDefinition;
  /** Every registered node type at every version, from the server. */
  types: EngineNodeType[];
  validate: (definition: EngineDefinition) => Promise<DefinitionValidation>;
  /** Rejects with the server's message on a 422. */
  publish: (definition: EngineDefinition) => Promise<DefinitionPublished>;
  publishing: boolean;
  /** Starts a live run on the live version, or a test run of the latest saved one; the page navigates to it. */
  startRun: (input: Record<string, unknown>, mode: RunMode) => Promise<void>;
  /** Starts a run from the start form the saved trigger declares (c-466); the page navigates to it. */
  startByHand?: (values: Record<string, unknown>, mode: RunMode) => Promise<void>;
  /** Where the saved versions stand: the latest one's stage, the live version, an open publish request. */
  lifecycle: Lifecycle;
  /** Sends the latest saved draft to Reviews. */
  requestPublish: (note: string) => Promise<{ status: string }>;
  setPaused: (paused: boolean) => Promise<unknown>;
  pausing: boolean;
  /** For a person who may not change the workflow: the graph shows, with no palette, editing, save, publish or pause. */
  readOnly?: boolean;
  /**
   * Lays out the editor's actions (lifecycle, Test run, Save version) and its canvas, so the page can put the actions
   * in its own header. Without it the actions sit in a row above the canvas.
   */
  frame?: (parts: { actions: React.ReactNode; canvas: React.ReactNode }) => React.ReactNode;
}

const SHORTCUTS: [string, string][] = [
  ['Add a step', 'N'],
  ['Open the selected step', 'Enter'],
  ['Remove the selected step', 'Delete'],
  ['Go to the trigger', 'S'],
  ['Fit the workflow', '1'],
  ['Reset the zoom', '0'],
  ['Zoom in or out', '+ / −'],
  ['Fullscreen', 'F'],
  ['Close the sheet or leave fullscreen', 'Esc'],
];

/** True while the person types in a field or works in a dialog, when a canvas key must not act. */
function typing(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null;
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return true;
  // The step sheet is not modal and leaves the canvas keys on; any other open dialog or menu owns the keyboard.
  return !!document.querySelector('[role="dialog"][data-state="open"]:not([data-testid="step-sheet"]), [role="menu"][data-state="open"], [role="listbox"]');
}

/** Steps upstream of `id` along the connections: the only ones whose output exists when it runs. */
function upstream(def: EngineDefinition, id: string): Set<string> {
  const seen = new Set<string>();
  const queue = [id];
  while (queue.length) {
    const at = queue.shift() as string;
    for (const c of def.connections) {
      if (c.to.node === at && !seen.has(c.from.node)) {
        seen.add(c.from.node);
        queue.push(c.from.node);
      }
    }
  }
  seen.delete(id);
  return seen;
}

const VALIDATE_DEBOUNCE_MS = 400;

/**
 * Applies an inspector edit. When the edit changes an `outputsFrom` list, connections leaving a port that no longer
 * exists are dropped: the canvas cannot draw them, so they could not be selected and deleted.
 */
function patchNode(d: EngineDefinition, id: string, patch: Partial<Pick<EngineNode, 'name' | 'parameters'>>, type: EngineNodeType | undefined): EngineDefinition {
  const nodes = d.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n));
  if (!type?.outputsFrom || !patch.parameters) return { ...d, nodes };
  const before = new Set(outPorts(type, d.nodes.find((n) => n.id === id)?.parameters).map((p) => p.name));
  const after = new Set(outPorts(type, patch.parameters).map((p) => p.name));
  const connections = d.connections.filter((c) => c.from.node !== id || !before.has(c.from.port) || after.has(c.from.port));
  return { ...d, nodes, connections };
}

function EditorInner({ definition: initial, types, validate, publish, publishing, startRun, startByHand, lifecycle, requestPublish, setPaused, pausing, readOnly = false, frame }: DefinitionEditorProps) {
  const [def, setDef] = React.useState<EngineDefinition>(() => withPositions(initial));
  const [dirty, setDirty] = React.useState(false);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  // The step whose sheet is open; clicking another step while it is open moves the sheet there.
  const [sheetId, setSheetId] = React.useState<string | null>(null);
  const [validation, setValidation] = React.useState<DefinitionValidation | null>(null);
  const [checking, setChecking] = React.useState(true);
  const [validateError, setValidateError] = React.useState<string | null>(null);
  const [runOpen, setRunOpen] = React.useState(false);
  const [publishOpen, setPublishOpen] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(() => initial.nodes.length === 0);
  const [checksOpen, setChecksOpen] = React.useState(false);
  const [fullscreen, setFullscreen] = React.useState(false);
  const canvasRef = React.useRef<HTMLDivElement>(null);
  const flow = useReactFlow();

  const typeIndex = React.useMemo(() => indexTypes(types), [types]);
  const typeOf = React.useCallback((n: EngineNode) => typeIndex.get(typeKey(n.type, n.typeVersion)), [typeIndex]);

  const change = React.useCallback((next: (d: EngineDefinition) => EngineDefinition) => {
    setDef(next);
    setDirty(true);
  }, []);

  // The server's checks, on load and after each change; a response for an older definition is dropped.
  const seq = React.useRef(0);
  const loaded = React.useRef(false);
  const validateRef = React.useRef(validate);
  React.useEffect(() => {
    validateRef.current = validate;
  }, [validate]);
  React.useEffect(() => {
    const mine = ++seq.current;
    setChecking(true);
    const t = window.setTimeout(
      () => {
        validateRef.current(def)
          .then((v) => {
            if (mine !== seq.current) return;
            setValidation(v);
            setValidateError(null);
          })
          .catch((e: unknown) => {
            if (mine === seq.current) setValidateError(e instanceof Error ? e.message : 'The check request failed');
          })
          .finally(() => {
            if (mine === seq.current) setChecking(false);
          });
      },
      loaded.current ? VALIDATE_DEBOUNCE_MS : 0,
    );
    loaded.current = true;
    return () => window.clearTimeout(t);
  }, [def]);

  const errorNodes = React.useMemo(() => new Set((validation?.checks ?? []).filter((c) => c.level === 'error' && c.node).map((c) => c.node as string)), [validation]);
  // A warning (a fork with no Join, a mapping to a field the step never outputs) marks its step but never blocks a save.
  const warnNodes = React.useMemo(() => new Set((validation?.checks ?? []).filter((c) => c.level === 'warning' && c.node).map((c) => c.node as string)), [validation]);

  // Drawn ports per node, from the server type; edges are only drawn between ports that exist.
  const ports = React.useMemo(() => {
    const m = new Map<string, { inputs: Set<string>; outputs: Set<string> }>();
    for (const n of def.nodes) {
      const t = typeOf(n);
      m.set(n.id, { inputs: new Set(t ? inPorts(t).map((p) => p.name) : []), outputs: new Set(t ? outPorts(t, n.parameters).map((p) => p.name) : []) });
    }
    return m;
  }, [def.nodes, typeOf]);

  const [nodes, setNodes, applyNodeChanges] = useNodesState<DefinitionFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // React Flow keeps measurements and drag state on its node objects, so the definition is mapped onto the previous
  // objects instead of replacing them.
  React.useEffect(() => {
    setNodes((prev) => {
      const byId = new Map(prev.map((p) => [p.id, p]));
      return def.nodes.map((n) => {
        const t = typeOf(n);
        const old = byId.get(n.id);
        return {
          ...old,
          id: n.id,
          type: 'definition' as const,
          position: n.position ?? old?.position ?? { x: 0, y: 0 },
          selected: n.id === selectedId,
          data: {
            nodeId: n.id,
            title: n.name || t?.label || n.id,
            typeLabel: t ? t.label : `${n.type} · version ${n.typeVersion}`,
            repeats: repeatsOver(n.parameters, def.nodes),
            group: t?.group ?? null,
            inputs: t ? inPorts(t) : [],
            outputs: t ? outPorts(t, n.parameters) : [],
            unknown: !t,
            hasError: errorNodes.has(n.id),
            hasWarning: warnNodes.has(n.id),
            typeId: n.type,
          },
        };
      });
    });
  }, [def.nodes, typeOf, selectedId, errorNodes, setNodes]);

  React.useEffect(() => {
    setEdges((prev) => {
      const selected = new Set(prev.filter((e) => e.selected).map((e) => e.id));
      return def.connections
        .filter((c) => ports.get(c.from.node)?.outputs.has(c.from.port) && ports.get(c.to.node)?.inputs.has(c.to.port))
        .map((c) => {
          const id = connectionId(c);
          return { id, source: c.from.node, sourceHandle: c.from.port, target: c.to.node, targetHandle: c.to.port, type: 'smoothstep', selected: selected.has(id) };
        });
    });
  }, [def.connections, ports, setEdges]);

  // Positions are written back once a drag ends, for every node the drag moved (a selection drag moves several).
  const onNodeDragStop = React.useCallback(
    (_: unknown, __: unknown, dragged: DefinitionFlowNode[]) => {
      const moved = new Map(dragged.map((n) => [n.id, { x: n.position.x, y: n.position.y }]));
      change((d) => ({ ...d, nodes: d.nodes.map((n) => (moved.has(n.id) ? { ...n, position: moved.get(n.id) } : n)) }));
    },
    [change],
  );

  const onConnect = React.useCallback(
    (c: Connection) => {
      if (!c.sourceHandle || !c.targetHandle) return;
      const next = { from: { node: c.source, port: c.sourceHandle }, to: { node: c.target, port: c.targetHandle } };
      change((d) => (d.connections.some((x) => connectionId(x) === connectionId(next)) ? d : { ...d, connections: [...d.connections, next] }));
    },
    [change],
  );

  const removeNodes = React.useCallback(
    (ids: Set<string>) => {
      if (!ids.size) return;
      change((d) => ({ ...d, nodes: d.nodes.filter((n) => !ids.has(n.id)), connections: d.connections.filter((c) => !ids.has(c.from.node) && !ids.has(c.to.node)) }));
      setSelectedId((cur) => (cur && ids.has(cur) ? null : cur));
      setSheetId((cur) => (cur && ids.has(cur) ? null : cur));
    },
    [change],
  );

  const onDelete: OnDelete<DefinitionFlowNode, Edge> = React.useCallback(
    ({ nodes: gone, edges: goneEdges }) => {
      const edgeIds = new Set(goneEdges.map((e) => e.id));
      if (edgeIds.size) change((d) => ({ ...d, connections: d.connections.filter((c) => !edgeIds.has(connectionId(c))) }));
      removeNodes(new Set(gone.map((n) => n.id)));
    },
    [change, removeNodes],
  );

  const addNode = (type: EngineNodeType) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    const centre = rect ? flow.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }) : { x: 0, y: 0 };
    const offset = (def.nodes.length % 5) * 24;
    const id = uniqueNodeId(type.id, def.nodes);
    const node: EngineNode = { id, type: type.id, typeVersion: type.version, name: type.label, position: { x: Math.round(centre.x - 120 + offset), y: Math.round(centre.y - 40 + offset) } };
    change((d) => ({ ...d, nodes: [...d.nodes, node] }));
    setSelectedId(id);
    setSheetId(id);
  };

  const opened = def.nodes.find((n) => n.id === sheetId) ?? null;
  const steps: StepRefs = React.useMemo(() => {
    if (!opened) return { all: [], earlier: [] };
    const ref = (n: EngineNode): StepRef => ({ id: n.id, label: n.name || typeOf(n)?.label || n.id, type: n.type });
    const before = upstream(def, opened.id);
    const others = def.nodes.filter((n) => n.id !== opened.id);
    return { all: others.map(ref), earlier: others.filter((n) => before.has(n.id)).map(ref) };
  }, [def, opened, typeOf]);
  // Steps in the order they run, left to right then top to bottom; the sheet's previous and next follow it.
  const runOrder = React.useMemo(() => [...def.nodes].sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0) || (a.position?.y ?? 0) - (b.position?.y ?? 0)).map((n) => n.id), [def.nodes]);
  const nodeName = React.useCallback((id: string) => def.nodes.find((n) => n.id === id)?.name || id, [def.nodes]);

  const selectNode = (id: string) => {
    setSelectedId(id);
    setSheetId((cur) => (cur ? id : cur));
    const n = def.nodes.find((x) => x.id === id);
    if (!n?.position) return;
    const zoom = Math.max(flow.getZoom(), 0.8);
    // With the sheet open the step is centred in the part of the canvas the sheet leaves visible, so it is not hidden.
    const sheet = sheetId ? (document.querySelector('[data-testid="step-sheet"]')?.getBoundingClientRect().width ?? 0) : 0;
    flow.setCenter(n.position.x + 120 + sheet / 2 / zoom, n.position.y + 40, { zoom, duration: 300 });
  };

  // The step sheet sits over the canvas only, leaving the page header (Save version, Test run) uncovered.
  React.useEffect(() => {
    const root = document.documentElement;
    const place = () => root.style.setProperty('--step-sheet-top', `${Math.max(0, Math.round(canvasRef.current?.getBoundingClientRect().top ?? 0))}px`);
    place();
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('resize', place);
      root.style.removeProperty('--step-sheet-top');
    };
  }, [fullscreen, sheetId]);

  const triggerId = React.useMemo(() => def.nodes.find((n) => typeOf(n)?.group === 'trigger')?.id, [def.nodes, typeOf]);
  const fit = React.useCallback(() => wholeFit(flow), [flow]);

  // The first view waits for React Flow to measure the nodes; fitting before that sees zero-sized nodes.
  const measured = useNodesInitialized();
  const fitted = React.useRef(false);
  React.useEffect(() => {
    if (measured && !fitted.current) {
      fitted.current = true;
      readableFit(flow, canvasRef.current, triggerId);
    }
  }, [measured, flow, triggerId]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      // The open sheet closes itself on Escape (it is the top layer); with no sheet open, Escape leaves fullscreen.
      if (e.key === 'Escape') {
        if (!sheetId && !typing(e)) setFullscreen(false);
        return;
      }
      if (typing(e)) return;
      const key = e.key.toLowerCase();
      if (key === 'f') setFullscreen((f) => !f);
      else if (key === '1') fit();
      else if (key === '0') void flow.zoomTo(1);
      else if (key === '+' || key === '=') void flow.zoomIn();
      else if (key === '-' || key === '_') void flow.zoomOut();
      else if (key === 's' && triggerId) selectNode(triggerId);
      else if (key === 'n' && !readOnly) setPaletteOpen(true);
      else if (key === 'enter' && selectedId) setSheetId(selectedId);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const save = async () => {
    try {
      const p = await publish(def);
      setDirty(false);
      toast.success(p.created ? `Saved as version ${p.version}` : `No changes since version ${p.version}`);
    } catch (e) {
      // A refused publish carries the server's checks; show them on the canvas and in the panel, not only as a toast.
      const checks = e instanceof ApiError ? (e.details?.checks as DefinitionCheck[] | undefined) : undefined;
      if (checks) setValidation({ ok: false, workflowId: def.id, digest: validation?.digest ?? null, checks });
      toast.error(e instanceof Error ? e.message : 'The version was not saved');
    }
  };

  // Saving makes a new version, so it needs a change since the last save as well as a valid definition.
  const canSave = dirty && !!validation?.ok && !checking && !validateError;

  const errorCount = (validation?.checks ?? []).filter((c) => c.level === 'error').length;
  const warningCount = (validation?.checks ?? []).filter((c) => c.level === 'warning').length;

  const actions = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {!readOnly && <LifecycleActions lifecycle={lifecycle} dirty={dirty} onPublish={() => setPublishOpen(true)} onSetPaused={setPaused} pausing={pausing} />}
      {/* Starting any run is a builder's or admin's step (runs/start, c-122); the server refuses the rest, so the
          button shows only to them. */}
      {!readOnly && (
        <Button type="button" variant="outline" onClick={() => setRunOpen(true)} data-testid="definition-start-run">
          <Play /> {lifecycle.liveVersion !== null && !lifecycle.paused ? 'Start run' : 'Test run'}
        </Button>
      )}
      {!readOnly && (
        <LoadingButton type="button" onClick={save} disabled={!canSave} isLoading={publishing} loadingText="Saving…" data-testid="definition-save">
          <Save /> Save version
        </LoadingButton>
      )}
    </div>
  );

  const canvas = (
    <div
      ref={canvasRef}
      className={cn('relative min-h-[28rem] min-w-0 flex-1 overflow-hidden rounded-xl border bg-muted/30', fullscreen && 'fixed inset-0 z-40 min-h-0 rounded-none border-0 bg-background')}
      data-testid="definition-canvas"
      data-fullscreen={fullscreen ? 'true' : undefined}
    >
      <ReactFlow<DefinitionFlowNode, Edge>
        nodes={nodes}
        edges={edges}
        nodeTypes={definitionNodeTypes}
        onNodesChange={applyNodeChanges}
        onEdgesChange={onEdgesChange}
        onNodeDragStop={onNodeDragStop}
        onConnect={onConnect}
        onDelete={onDelete}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        deleteKeyCode={readOnly ? null : undefined}
        // One click opens the step's settings; React Flow reports a drag as no click, so moving a step leaves it shut.
        onNodeClick={(_, n) => {
          setSelectedId(n.id);
          setSheetId(n.id);
        }}
        onPaneClick={() => setSelectedId(null)}
        defaultEdgeOptions={{ type: 'smoothstep', style: { stroke: 'var(--muted-foreground)', strokeWidth: 1.5 } }}
        minZoom={MIN_ZOOM}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
        {!readOnly && (
          <Panel position="top-left">
            <StepList
              types={types}
              open={paletteOpen}
              onOpenChange={setPaletteOpen}
              startTab={def.nodes.length === 0 ? 'trigger' : 'all'}
              onAdd={(t) => {
                addNode(t);
                setPaletteOpen(false);
              }}
            />
          </Panel>
        )}
        <Panel position="top-right" className="flex items-center gap-2">
          <div className="flex items-center gap-2">
            <Popover>
              <PopoverTrigger asChild>
                <Button type="button" variant="outline" size="icon" className="size-9 bg-card max-sm:hidden" aria-label="Keyboard shortcuts" title="Keyboard shortcuts">
                  <Keyboard />
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-72">
                <p className="mb-1 text-sm font-medium">Keyboard shortcuts</p>
                <Rows>
                  {SHORTCUTS.map(([what, key]) => (
                    <Row
                      key={what}
                      title={what}
                      trailing={
                        <Badge variant="outline" className="font-mono">
                          {key}
                        </Badge>
                      }
                    />
                  ))}
                </Rows>
              </PopoverContent>
            </Popover>
            <CanvasControls isFullscreen={fullscreen} onToggleFullscreen={() => setFullscreen((f) => !f)} onFit={fit} />
          </div>
        </Panel>
        <Panel position="bottom-left">
          <Popover open={checksOpen} onOpenChange={setChecksOpen}>
            <PopoverTrigger asChild>
              <Button type="button" variant="outline" size="sm" className={cn('bg-card shadow-sm', errorCount > 0 && 'border-destructive text-destructive')} data-testid="definition-checks-count">
                {errorCount > 0 ? <AlertTriangle /> : warningCount > 0 ? <AlertTriangle className="text-warning-text" /> : <CheckCircle2 className="text-success-text" />}
                {checking && !validation ? 'Checking…' : errorCount > 0 ? (errorCount === 1 ? '1 error' : `${errorCount} errors`) : warningCount > 0 ? (warningCount === 1 ? '1 warning' : `${warningCount} warnings`) : 'No problems'}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" side="top" className="w-96 max-w-[calc(100vw-2rem)] p-0">
              <ChecksPanel
                validation={validation}
                checking={checking}
                failed={validateError}
                nodeName={nodeName}
                onSelectNode={(id) => {
                  setChecksOpen(false);
                  selectNode(id);
                }}
              />
            </PopoverContent>
          </Popover>
        </Panel>
        {def.nodes.length > 0 && (
          <MiniMap
            pannable
            zoomable
            ariaLabel="Overview of the workflow"
            className="!rounded-lg !border !bg-card max-sm:!hidden"
            bgColor="var(--card)"
            maskColor="color-mix(in oklch, var(--muted) 60%, transparent)"
            nodeColor="var(--border)"
            nodeStrokeColor="var(--muted-foreground)"
            nodeStrokeWidth={2}
            nodeBorderRadius={8}
          />
        )}
      </ReactFlow>
    </div>
  );

  return (
    <>
      {frame ? (
        frame({ actions, canvas })
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          {actions}
          {canvas}
        </div>
      )}
      <StepSheet
        node={opened}
        type={opened ? typeOf(opened) : undefined}
        workflowId={def.id}
        steps={steps}
        checks={(validation?.checks ?? []).filter((c) => c.node === opened?.id)}
        order={runOrder}
        readOnly={readOnly}
        onClose={() => setSheetId(null)}
        onMove={selectNode}
        onChange={(patch) => opened && change((d) => patchNode(d, opened.id, patch, typeOf(opened)))}
        onDelete={() => opened && removeNodes(new Set([opened.id]))}
      />
      <StartDefinitionRunDialog open={runOpen} onOpenChange={setRunOpen} workflowName={def.name || def.id} latestVersion={lifecycle.version} liveVersion={lifecycle.liveVersion} paused={lifecycle.paused} onStart={startRun} startForm={lifecycle.startForm} onStartForm={startByHand} />
      <PublishDefinitionDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        version={lifecycle.version}
        liveVersion={lifecycle.liveVersion}
        onRequest={async (note) => {
          const r = await requestPublish(note);
          toast.success(r.status === 'approved' ? `Version ${lifecycle.version} is live` : `Version ${lifecycle.version} sent for review`);
        }}
      />
    </>
  );
}

/** The v2 definition editor: types, ports and checks all come from the server. */
export function DefinitionEditor(props: DefinitionEditorProps) {
  return (
    <ReactFlowProvider>
      <EditorInner {...props} />
    </ReactFlowProvider>
  );
}
