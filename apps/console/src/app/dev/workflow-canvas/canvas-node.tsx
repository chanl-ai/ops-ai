'use client';

import { memo } from 'react';
import { Handle, type Node, type NodeProps, Position } from '@xyflow/react';
import { AlertTriangle, Braces, Flag, GitBranch, HelpCircle, Sparkles, UserCheck, Wrench, Zap, type LucideIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { DefinitionNodeData } from '@/components/workflows/definition-editor/definition-node';
import { cn } from '@/lib/utils';

/**
 * The step as the larger canvas draws it: an icon tile per group, the trigger marked where the run starts. It takes
 * the shared `DefinitionNodeData`, so in the build it replaces the body of `DefinitionNode` and the run view keeps
 * drawing the same node.
 */
export type CanvasNodeData = DefinitionNodeData & { typeId: string };
export type CanvasFlowNode = Node<CanvasNodeData, 'canvas'>;

const GROUP: Record<string, { icon: LucideIcon; tile: string }> = {
  trigger: { icon: Zap, tile: 'bg-primary/10 text-primary' },
  data: { icon: Braces, tile: 'bg-chart-1/15 text-chart-1' },
  flow: { icon: GitBranch, tile: 'bg-muted text-muted-foreground' },
  action: { icon: Wrench, tile: 'bg-chart-3/15 text-chart-3' },
  ai: { icon: Sparkles, tile: 'bg-chart-2/15 text-chart-2' },
  human: { icon: UserCheck, tile: 'bg-warning/15 text-warning-text' },
};
const END = { icon: Flag, tile: 'bg-success/15 text-success-text' };

export function groupLook(group: string | null, typeId?: string) {
  if (typeId === 'ops.flow.end') return END;
  return (group && GROUP[group]) || { icon: HelpCircle, tile: 'bg-muted text-muted-foreground' };
}

const HANDLE = '!size-2.5 !border-2 !border-background !bg-muted-foreground';

export const CanvasNode = memo(function CanvasNode({ data, selected }: NodeProps<CanvasFlowNode>) {
  const look = groupLook(data.group, data.typeId);
  const Icon = look.icon;
  const trigger = data.group === 'trigger';
  const rows = Math.max(data.inputs.length, data.outputs.length);
  const broken = data.hasError || data.unknown;
  return (
    <div
      data-testid="canvas-node"
      data-node-id={data.nodeId}
      data-error={broken ? 'true' : undefined}
      className={cn(
        'w-60 rounded-xl border bg-card text-card-foreground shadow-sm transition-shadow hover:shadow-md',
        trigger && 'border-2 border-dashed border-primary/50',
        broken && 'border-2 border-destructive',
        selected && 'ring-2 ring-primary ring-offset-2 ring-offset-background',
      )}
    >
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.tile)}>
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{data.title}</p>
          <p className="truncate text-xs text-muted-foreground">{data.typeLabel}</p>
        </div>
        {broken && <AlertTriangle className="size-4 shrink-0 text-destructive" aria-label="Has an error" />}
      </div>
      {trigger && (
        <div className="px-3 pb-2">
          <Badge variant="outline" className="border-primary/40 text-primary">
            Starts here
          </Badge>
        </div>
      )}
      {rows > 0 && (
        <div className="flex flex-col gap-1 border-t py-2">
          {Array.from({ length: rows }).map((_, i) => {
            const input = data.inputs[i];
            const output = data.outputs[i];
            return (
              <div key={i} className="relative flex min-h-5 items-center justify-between gap-2 px-3 text-xs">
                {input ? (
                  <>
                    <Handle type="target" position={Position.Left} id={input.name} className={HANDLE} />
                    <span className="min-w-0 truncate text-muted-foreground">{input.label}</span>
                  </>
                ) : (
                  <span />
                )}
                {output && (
                  <>
                    <span className="min-w-0 truncate text-right">{output.label}</span>
                    <Handle type="source" position={Position.Right} id={output.name} className={HANDLE} />
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});

export const canvasNodeTypes = { canvas: CanvasNode };
