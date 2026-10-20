'use client';

import * as React from 'react';
import { Background, BackgroundVariant, type Edge, Panel, ReactFlow, ReactFlowProvider } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { connectionId, indexTypes, inPorts, outPorts, repeatsOver, typeKey, withPositions } from '@/components/workflows/definition-editor/graph';
import { type DefinitionFlowNode, definitionNodeTypes, type RunMark } from '@/components/workflows/definition-editor/definition-node';
import { CanvasControls } from '@/components/workflows/canvas-controls';
import type { EngineDefinition, EngineNodeType, EngineRunStep } from '@/lib/types/engine';

const TERMINAL = ['succeeded', 'failed', 'cancelled'];

/** What one node did in a run, from its last step (a node run in a loop shows its latest iteration). */
export function runMark(step: EngineRunStep | undefined, runStatus: string): RunMark {
  if (!step) return TERMINAL.includes(runStatus) ? 'skipped' : 'not_reached';
  if (step.status === 'ok' || step.status === 'pinned') return 'passed';
  if (step.status === 'error') return 'failed';
  if (step.status === 'abandoned') return 'stopped';
  return step.status === 'waiting' ? 'waiting' : 'running';
}

export interface RunCanvasProps {
  definition: EngineDefinition;
  types: EngineNodeType[];
  steps: EngineRunStep[];
  runStatus: string;
  /** Opens the step sheet on this step's index in `steps`. */
  onOpenStep: (index: number) => void;
}

/**
 * A run on its workflow's own canvas (c-097): the editor's nodes and edges, read-only, each node marked with what its
 * step did, and the paths the run took drawn solid. Clicking a node that ran opens its input, output and attempts.
 */
function Canvas({ definition, types, steps, runStatus, onOpenStep }: RunCanvasProps) {
  const typeIndex = React.useMemo(() => indexTypes(types), [types]);
  // The last step per node: the order steps started in, so a later iteration wins.
  const lastStep = React.useMemo(() => {
    const m = new Map<string, number>();
    steps.forEach((s, i) => m.set(s.nodeId, i));
    return m;
  }, [steps]);
  // The editor's layout, so a definition the server stored unplaced (every node at 0,0) is drawn as the editor draws it.
  const laid = React.useMemo(() => withPositions(definition), [definition]);

  const nodes: DefinitionFlowNode[] = laid.nodes.map((n) => {
    const t = typeIndex.get(typeKey(n.type, n.typeVersion));
    const index = lastStep.get(n.id);
    return {
      id: n.id,
      type: 'definition',
      position: n.position ?? { x: 0, y: 0 },
      draggable: false,
      connectable: false,
      data: {
        nodeId: n.id,
        title: n.name || t?.label || n.id,
        typeLabel: t ? t.label : `${n.type} · version ${n.typeVersion}`,
        repeats: repeatsOver(n.parameters, definition.nodes),
        group: t?.group ?? null,
        inputs: t ? inPorts(t) : [],
        outputs: t ? outPorts(t, n.parameters) : [],
        unknown: !t,
        hasError: false,
        typeId: n.type,
        run: runMark(index === undefined ? undefined : steps[index], runStatus),
      },
    };
  });
  const edges: Edge[] = definition.connections.map((c) => {
    const from = lastStep.get(c.from.node);
    // Taken: the source step left by this port and the target ran.
    const taken = from !== undefined && steps[from].port === c.from.port && lastStep.has(c.to.node);
    return {
      id: connectionId(c),
      source: c.from.node,
      sourceHandle: c.from.port,
      target: c.to.node,
      targetHandle: c.to.port,
      type: 'smoothstep',
      animated: taken && runStatus === 'running',
      style: taken ? { strokeWidth: 2.5, stroke: 'var(--primary)' } : { opacity: 0.35, strokeDasharray: '4 4' },
      data: { taken },
    };
  });

  return (
    <div className="h-112 overflow-hidden rounded-lg border" data-testid="run-canvas">
      <ReactFlow<DefinitionFlowNode, Edge>
        nodes={nodes}
        edges={edges}
        nodeTypes={definitionNodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        deleteKeyCode={null}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
        className="bg-muted/30"
        onNodeClick={(_, n) => {
          const index = lastStep.get(n.id);
          if (index !== undefined) onOpenStep(index);
        }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
        <Panel position="top-right">
          <CanvasControls />
        </Panel>
      </ReactFlow>
    </div>
  );
}

export function RunCanvas(props: RunCanvasProps) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
