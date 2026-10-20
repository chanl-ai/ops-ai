'use client';

import * as React from 'react';
import { Background, BackgroundVariant, type Edge, MiniMap, Panel, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AlertTriangle, CheckCircle2, Keyboard, PanelLeftClose, Plus, Trash2, Workflow } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { FormField } from '@/components/shared/form-field';
import { KeyValues, Row, Rows, Section } from '@/components/shared/surface';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { CanvasControls } from '@/components/workflows/canvas-controls';
import { ChecksPanel } from '@/components/workflows/definition-editor/checks-panel';
import { connectionId, indexTypes, inPorts, outPorts, paletteGroups, typeKey } from '@/components/workflows/definition-editor/graph';
import { NodeSettingsForm, type StepRef, type StepRefs } from '@/components/workflows/definition-editor/node-form';
import { useValidateDefinition } from '@/hooks/engine-queries';
import type { DefinitionValidation, EngineDefinition, EngineNode, EngineNodeType } from '@/lib/types/engine';
import { cn } from '@/lib/utils';

import { type CanvasFlowNode, canvasNodeTypes, groupLook } from './canvas-node';

export type Scene = 'empty' | 'large' | 'adding' | 'step' | 'trigger' | 'error' | 'phone';

const GROUP_LABEL: Record<string, string> = { trigger: 'Triggers', data: 'Data', flow: 'Flow', action: 'Actions', ai: 'AI', human: 'People' };
/** Triggers first, since a workflow starts with one; then the steps in the order a builder usually reaches for them. */
const GROUP_ORDER = ['trigger', 'ai', 'action', 'human', 'flow', 'data'];
const rank = (g: string) => (GROUP_ORDER.indexOf(g) + GROUP_ORDER.length + 1) % (GROUP_ORDER.length + 1);
const STEP_KIND: Record<string, string> = { trigger: 'Trigger', data: 'Data', flow: 'Flow', action: 'Action', ai: 'AI', human: 'Person' };

const SHORTCUTS: [string, string][] = [
  ['N', 'Add a step'],
  ['Enter', 'Open the selected step'],
  ['Delete', 'Remove the selected step'],
  ['S', 'Go to the trigger'],
  ['1', 'Fit the workflow'],
  ['0', 'Reset the zoom'],
  ['+ / −', 'Zoom in or out'],
  ['F', 'Fullscreen'],
  ['Esc', 'Close a sheet or leave fullscreen'],
];

/** Steps upstream of `id`: the only ones whose output exists when it runs. */
function upstream(def: EngineDefinition, id: string): Set<string> {
  const seen = new Set<string>();
  const queue = [id];
  while (queue.length) {
    const here = queue.shift() as string;
    for (const c of def.connections) if (c.to.node === here && !seen.has(c.from.node)) (seen.add(c.from.node), queue.push(c.from.node));
  }
  seen.delete(id);
  return seen;
}

/** Steps in the order they run: by column, then top to bottom. Previous and next in a step's sheet follow it. */
const runOrder = (def: EngineDefinition) => [...def.nodes].sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0) || (a.position?.y ?? 0) - (b.position?.y ?? 0));

/** The floating step selector over the canvas's top-left corner; collapsed, it is one button. */
function StepSelector({ types, open, onOpenChange, onAdd }: { types: EngineNodeType[]; open: boolean; onOpenChange: (open: boolean) => void; onAdd: (t: EngineNodeType) => void }) {
  if (!open) {
    return (
      <Button type="button" variant="outline" size="sm" className="bg-card shadow-sm" onClick={() => onOpenChange(true)} data-testid="step-selector-open">
        <Plus /> <span className="max-sm:sr-only">Add a step</span>
        <Badge variant="outline" className="font-mono max-sm:hidden">
          N
        </Badge>
      </Button>
    );
  }
  return (
    <div className="flex w-72 max-w-[calc(100vw-3rem)] flex-col overflow-hidden rounded-xl border bg-popover shadow-lg" data-testid="step-selector">
      <div className="flex items-center justify-between border-b py-1.5 pr-1.5 pl-3">
        <p className="text-sm font-medium">Add a step</p>
        <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Close the step list" onClick={() => onOpenChange(false)}>
          <PanelLeftClose />
        </Button>
      </div>
      <Command>
        <CommandInput placeholder="Search steps" />
        <CommandList className="max-h-[min(26rem,55vh)]">
          <CommandEmpty>No step matches.</CommandEmpty>
          {[...paletteGroups(types)].sort(([a], [b]) => rank(a) - rank(b)).map(([group, list]) => (
            <CommandGroup key={group} heading={GROUP_LABEL[group] ?? group}>
              {list.map((t) => {
                const look = groupLook(t.group, t.id);
                const Icon = look.icon;
                return (
                  <CommandItem key={t.id} value={`${t.label} ${t.description}`} onSelect={() => onAdd(t)} className="items-start gap-2.5 py-2">
                    <span className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md', look.tile)}>
                      <Icon className="size-3.5" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{t.label}</span>
                      <span className="line-clamp-2 text-xs text-muted-foreground">{t.description}</span>
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          ))}
        </CommandList>
      </Command>
    </div>
  );
}

/** The step's sheet: name, the form its type generates, and for the trigger how a run starts. */
function StepSheet({
  def,
  node,
  type,
  checks,
  onClose,
  onMove,
  onChange,
}: {
  def: EngineDefinition;
  node: EngineNode | null;
  type: EngineNodeType | undefined;
  checks: DefinitionValidation | null;
  onClose: () => void;
  onMove: (id: string) => void;
  onChange: (id: string, patch: Partial<EngineNode>) => void;
}) {
  const order = runOrder(def);
  const index = node ? order.findIndex((n) => n.id === node.id) : -1;
  const steps: StepRefs = React.useMemo(() => {
    if (!node) return { all: [], earlier: [] };
    const ref = (n: EngineNode): StepRef => ({ id: n.id, label: n.name || n.id, type: n.type });
    const before = upstream(def, node.id);
    const others = def.nodes.filter((n) => n.id !== node.id);
    return { all: others.map(ref), earlier: others.filter((n) => before.has(n.id)).map(ref) };
  }, [def, node]);
  const errors = (checks?.checks ?? []).filter((c) => c.node === node?.id && c.level === 'error');
  const trigger = type?.group === 'trigger';
  const schema = (node?.parameters?.inputSchema ?? {}) as { properties?: Record<string, { type?: string; description?: string }>; required?: string[] };
  const look = groupLook(type?.group ?? null, node?.type);

  return (
    <DetailSheet
      open={!!node}
      onOpenChange={(o) => !o && onClose()}
      widthClass="sm:max-w-xl"
      testId="step-sheet"
      scrollKey={node?.id}
      title={node?.name || node?.id || ''}
      description={type ? `${type.label} · ${type.description}` : undefined}
      tags={
        node && (
          <>
            <Badge variant="outline" className={look.tile}>
              {STEP_KIND[type?.group ?? ''] ?? type?.group}
            </Badge>
            {type && type.effects !== 'none' && <Badge variant="outline">Effects: {type.effects}</Badge>}
            {errors.length > 0 && <Badge variant="destructive">{errors.length === 1 ? '1 error' : `${errors.length} errors`}</Badge>}
          </>
        )
      }
      navigation={
        index >= 0
          ? {
              currentIndex: index,
              totalCount: order.length,
              onPrev: index > 0 ? () => onMove(order[index - 1].id) : undefined,
              onNext: index < order.length - 1 ? () => onMove(order[index + 1].id) : undefined,
            }
          : undefined
      }
      footerActions={
        node && (
          <Button type="button" variant="ghost" size="sm" className="text-destructive">
            <Trash2 /> Delete step
          </Button>
        )
      }
    >
      {node && (
        <div className="flex flex-col gap-5">
          {errors.length > 0 && (
            <Alert variant="destructive" data-testid="step-sheet-errors">
              <AlertTriangle />
              <AlertTitle>This step stops the workflow from saving</AlertTitle>
              <AlertDescription>
                {errors.map((c) => (
                  <p key={`${c.code}-${c.message}`}>{c.message}</p>
                ))}
              </AlertDescription>
            </Alert>
          )}
          {trigger && (
            <Section title="How it starts" description="Every run of this workflow begins here.">
              <KeyValues
                rows={[
                  ['From an app', <span className="text-sm">An authenticated call that starts a run with this workflow’s id, <code className="font-mono text-xs">POST /v1/runs</code></span>],
                  ['From an agent', <span className="text-sm">An agent that has this workflow as a tool, <code className="font-mono text-xs">workflow__{def.id}</code></span>],
                  ['From here', 'Test run, with an input you type'],
                ]}
              />
            </Section>
          )}
          {trigger && (
            <Section title="Run input" description="What a run must send; checked against the input schema before the first step.">
              <KeyValues
                rows={Object.entries(schema.properties ?? {}).map(([name, p]) => [
                  name,
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="font-mono">
                      {p.type ?? 'any'}
                    </Badge>
                    {schema.required?.includes(name) && <Badge variant="secondary">required</Badge>}
                    <span className="text-muted-foreground">{p.description}</span>
                  </span>,
                ])}
              />
            </Section>
          )}
          <FormField id="sheet-step-name" label="Name" optional>
            <Input id="sheet-step-name" value={node.name ?? ''} onChange={(e) => onChange(node.id, { name: e.target.value || undefined })} />
          </FormField>
          {type?.ui?.order.length ? (
            <NodeSettingsForm form={type.ui} schema={type.parameters} value={node.parameters ?? {}} steps={steps} idPrefix={`sheet-${node.id}`} onChange={(parameters) => onChange(node.id, { parameters })} />
          ) : null}
        </div>
      )}
    </DetailSheet>
  );
}

function ShortcutsButton() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="icon" className="size-9 bg-card max-sm:hidden" aria-label="Keyboard shortcuts">
          <Keyboard />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72">
        <p className="mb-1 text-sm font-medium">Keyboard shortcuts</p>
        <Rows>
          {SHORTCUTS.map(([k, what]) => (
            <Row
              key={k}
              title={what}
              trailing={
                <Badge variant="outline" className="font-mono">
                  {k}
                </Badge>
              }
            />
          ))}
        </Rows>
      </PopoverContent>
    </Popover>
  );
}

function ChecksButton({ validation, checking, def }: { validation: DefinitionValidation | null; checking: boolean; def: EngineDefinition }) {
  const errors = (validation?.checks ?? []).filter((c) => c.level === 'error').length;
  const nodeName = (id: string) => def.nodes.find((n) => n.id === id)?.name || id;
  return (
    <Popover defaultOpen={false}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" className={cn('bg-card shadow-sm', errors > 0 && 'border-destructive text-destructive')} data-testid="canvas-checks">
          {errors > 0 ? <AlertTriangle /> : <CheckCircle2 className="text-success-text" />}
          {checking ? 'Checking…' : errors > 0 ? (errors === 1 ? '1 error' : `${errors} errors`) : 'No problems'}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" className="w-96 max-w-[calc(100vw-2rem)] p-0">
        <ChecksPanel validation={validation} checking={checking} failed={null} nodeName={nodeName} onSelectNode={() => undefined} />
      </PopoverContent>
    </Popover>
  );
}

function Canvas({ initial, types, scene }: { initial: EngineDefinition; types: EngineNodeType[]; scene: Scene }) {
  const [def, setDef] = React.useState(initial);
  const [selectorOpen, setSelectorOpen] = React.useState(scene === 'empty' || scene === 'adding');
  const [openId, setOpenId] = React.useState<string | null>(scene === 'step' ? 'assess' : scene === 'trigger' ? 'start' : scene === 'error' ? 'hold' : null);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [validation, setValidation] = React.useState<DefinitionValidation | null>(null);
  const { mutateAsync: validate, isPending: checking } = useValidateDefinition();
  const flow = useReactFlow();
  const typeIndex = React.useMemo(() => indexTypes(types), [types]);
  const typeOf = React.useCallback((n: EngineNode) => typeIndex.get(typeKey(n.type, n.typeVersion)), [typeIndex]);

  React.useEffect(() => {
    void validate(def).then(setValidation);
  }, [def, validate]);

  const errorNodes = React.useMemo(() => new Set((validation?.checks ?? []).filter((c) => c.level === 'error' && c.node).map((c) => c.node as string)), [validation]);
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasFlowNode>([]);
  React.useEffect(() => {
    setNodes((prev) => {
      const byId = new Map(prev.map((p) => [p.id, p]));
      return def.nodes.map((n) => {
        const t = typeOf(n);
        return {
          ...byId.get(n.id),
          id: n.id,
          type: 'canvas' as const,
          position: byId.get(n.id)?.position ?? n.position ?? { x: 0, y: 0 },
          selected: n.id === openId,
          data: {
            nodeId: n.id,
            typeId: n.type,
            title: n.name || t?.label || n.id,
            typeLabel: t ? t.label : `${n.type} · version ${n.typeVersion}`,
            group: t?.group ?? null,
            inputs: t ? inPorts(t) : [],
            outputs: t ? outPorts(t, n.parameters) : [],
            unknown: !t,
            hasError: errorNodes.has(n.id),
          },
        };
      });
    });
  }, [def.nodes, typeOf, openId, errorNodes, setNodes]);
  const edges: Edge[] = def.connections.map((c) => ({ id: connectionId(c), source: c.from.node, sourceHandle: c.from.port, target: c.to.node, targetHandle: c.to.port, type: 'smoothstep', style: { stroke: 'var(--muted-foreground)', strokeWidth: 1.5 } }));

  const goToTrigger = React.useCallback(() => {
    const t = def.nodes.find((n) => typeOf(n)?.group === 'trigger');
    if (t?.position) flow.setCenter(t.position.x + 120, t.position.y + 60, { zoom: 1 });
  }, [def.nodes, typeOf, flow]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      if (document.querySelector('[role="dialog"][data-state="open"]')) return;
      if (e.key === 'n' || e.key === 'N') (e.preventDefault(), setSelectorOpen(true));
      else if (e.key === 'f' || e.key === 'F') setFullscreen((f) => !f);
      else if (e.key === 'Escape') setFullscreen(false);
      else if (e.key === '1') void flow.fitView({ padding: 0.12 });
      else if (e.key === '0') void flow.zoomTo(1);
      else if (e.key === 's' || e.key === 'S') goToTrigger();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [flow, goToTrigger]);

  const addStep = (t: EngineNodeType) => {
    const id = `${t.id.split('.').pop()}_${def.nodes.length + 1}`;
    const centre = flow.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
    setDef((d) => ({ ...d, nodes: [...d.nodes, { id, type: t.id, typeVersion: t.version, name: t.label, position: { x: Math.round(centre.x - 120), y: Math.round(centre.y - 40) } }] }));
    setOpenId(id);
  };
  const open = def.nodes.find((n) => n.id === openId) ?? null;

  return (
    <div className={cn('relative min-h-[28rem] flex-1 overflow-hidden rounded-xl border bg-muted/30', fullscreen && 'fixed inset-0 z-40 rounded-none border-0 bg-background')} data-testid="workflow-canvas">
      <ReactFlow<CanvasFlowNode, Edge>
        nodes={nodes}
        edges={edges}
        nodeTypes={canvasNodeTypes}
        onNodesChange={onNodesChange}
        onNodeDoubleClick={(_, n) => setOpenId(n.id)}
        // On a phone the whole graph would fit at an unreadable zoom, so the canvas opens on the trigger instead.
        onInit={(rf) => {
          if (window.innerWidth >= 640) return;
          const t = def.nodes.find((n) => typeOf(n)?.group === 'trigger');
          if (t?.position) void rf.setCenter(t.position.x + 160, t.position.y + 60, { zoom: 0.75 });
        }}
        fitView={typeof window === 'undefined' || window.innerWidth >= 640}
        defaultEdgeOptions={{ type: 'smoothstep' }}
        fitViewOptions={{ padding: { top: '64px', right: '48px', bottom: '64px', left: selectorOpen ? '330px' : '48px' } }}
        minZoom={0.1}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
        <Panel position="top-left">
          <StepSelector types={types} open={selectorOpen} onOpenChange={setSelectorOpen} onAdd={addStep} />
        </Panel>
        <Panel position="top-right">
          <div className="flex items-center gap-2">
            <ShortcutsButton />
            <CanvasControls isFullscreen={fullscreen} onToggleFullscreen={() => setFullscreen((f) => !f)} />
          </div>
        </Panel>
        <Panel position="bottom-left">
          <ChecksButton validation={validation} checking={checking && !validation} def={def} />
        </Panel>
        {def.nodes.length > 0 && <MiniMap pannable zoomable className="!rounded-lg !border !bg-card max-sm:!hidden" bgColor="var(--card)" maskColor="color-mix(in oklch, var(--muted) 60%, transparent)" nodeColor="var(--border)" nodeStrokeColor="var(--muted-foreground)" nodeStrokeWidth={2} nodeBorderRadius={8} />}
        {def.nodes.length === 0 && (
          <Panel position="top-center" className="!top-1/3 max-sm:!top-auto max-sm:!bottom-16">
            <div className="rounded-xl border bg-card shadow-sm">
              <EmptyState icon={Workflow} title="Start with a trigger" description="Every workflow starts at one trigger: what calls it, and the input it takes. Pick one from Add a step, then add the steps it runs." />
            </div>
          </Panel>
        )}
      </ReactFlow>
      <StepSheet
        def={def}
        node={open}
        type={open ? typeOf(open) : undefined}
        checks={validation}
        onClose={() => setOpenId(null)}
        onMove={setOpenId}
        onChange={(id, patch) => setDef((d) => ({ ...d, nodes: d.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) }))}
      />
    </div>
  );
}

export function LargeCanvas(props: { initial: EngineDefinition; types: EngineNodeType[]; scene: Scene }) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
