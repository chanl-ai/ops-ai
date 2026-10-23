'use client';

import * as React from 'react';
import { Background, BackgroundVariant, type Edge, Panel, ReactFlow, ReactFlowProvider, useNodesInitialized, useNodesState, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { connectionId, definitionNodeData, indexTypes, typeKey } from '@/components/workflows/definition-editor/graph';
import { RoutedLines, routedEdgeTypes } from '@/components/workflows/definition-editor/routed-edge';
import { useLayout } from '@/components/workflows/layout/use-layout';
import { Skeleton } from '@/components/ui/skeleton';
import { type DefinitionFlowNode, definitionNodeTypes, type RunMark } from '@/components/workflows/definition-editor/definition-node';
import { CanvasControls } from '@/components/workflows/canvas-controls';
import { MIN_ZOOM, readableFit } from '@/components/workflows/definition-editor/canvas-view';
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
  // The editor's layout (layout/use-layout.ts), so a definition with unplaced steps is drawn as the editor draws it.
  const placed = useLayout(definition, types);
  const laid = placed ?? definition;

  const built = React.useMemo<DefinitionFlowNode[]>(
    () =>
      laid.nodes.map((n) => {
        const t = typeIndex.get(typeKey(n.type, n.typeVersion));
        const index = lastStep.get(n.id);
        return {
          id: n.id,
          type: 'definition',
          position: n.position ?? { x: 0, y: 0 },
          draggable: false,
          connectable: false,
          data: { ...definitionNodeData(n, t, definition.nodes), run: runMark(index === undefined ? undefined : steps[index], runStatus) },
        };
      }),
    [laid, typeIndex, lastStep, steps, runStatus, definition.nodes],
  );
  // Held in state so React Flow's measurements reach the nodes, which useNodesInitialized reads; a refetch maps onto the
  // previous objects, as the editor does, so they keep their measurements.
  const [nodes, setNodes, onNodesChange] = useNodesState<DefinitionFlowNode>(built);
  React.useEffect(() => {
    setNodes((prev) => {
      const byId = new Map(prev.map((p) => [p.id, p]));
      return built.map((b) => ({ ...byId.get(b.id), ...b }));
    });
  }, [built, setNodes]);
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
      type: 'routed',
      animated: taken && runStatus === 'running',
      style: taken ? { strokeWidth: 2.5, stroke: 'var(--primary)' } : { opacity: 0.35, strokeDasharray: '4 4' },
      data: { taken },
    };
  });

  // Opens as the editor does: fitted when the steps stay readable, else at a readable zoom from the trigger. Fitting
  // waits for React Flow to measure the nodes.
  const flow = useReactFlow();
  const canvasRef = React.useRef<HTMLDivElement>(null);
  const measured = useNodesInitialized();
  const triggerId = laid.nodes.find((n) => typeIndex.get(typeKey(n.type, n.typeVersion))?.group === 'trigger')?.id;
  const fitted = React.useRef(false);
  React.useEffect(() => {
    if (measured && placed && !fitted.current) {
      fitted.current = true;
      readableFit(flow, canvasRef.current, triggerId);
    }
  }, [measured, placed, flow, triggerId]);

  if (!placed) return <Skeleton className="h-112 rounded-lg" data-testid="run-canvas-loading" />;
  return (
    <div ref={canvasRef} className="h-112 overflow-hidden rounded-lg border" data-testid="run-canvas">
      <RoutedLines nodes={nodes}>
      <ReactFlow<DefinitionFlowNode, Edge>
        nodes={nodes}
        edges={edges}
        nodeTypes={definitionNodeTypes}
        edgeTypes={routedEdgeTypes}
        onNodesChange={onNodesChange}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        deleteKeyCode={null}
        minZoom={MIN_ZOOM}
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
      </RoutedLines>
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
