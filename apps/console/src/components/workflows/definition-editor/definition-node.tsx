'use client';

import { memo } from 'react';
import { Handle, type Node, type NodeProps, Position } from '@xyflow/react';
import { AlertTriangle, Braces, CheckCircle2, CircleDashed, CircleSlash, Clock, Flag, GitBranch, HelpCircle, Loader2, Repeat, Sparkles, UserCheck, Wrench, XCircle, Zap, type LucideIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import type { DrawnPort } from './graph';

export type DefinitionNodeData = {
  nodeId: string;
  title: string;
  /** The type's label, or the raw `type@version` when the server does not know it. */
  typeLabel: string;
  /** "for each <list> from <step>" on a step that repeats over a list; absent on one that runs once. */
  repeats?: string | null;
  /** The whole repeat line when `repeats` is shortened to fit; shown on hover. */
  repeatsFull?: string | null;
  group: string | null;
  inputs: DrawnPort[];
  outputs: DrawnPort[];
  unknown: boolean;
  hasError: boolean;
  hasWarning?: boolean;
  /** The node's type id; an End step is drawn as an outcome. */
  typeId?: string;
  /** The height the layout gave this step (layout/node-size.ts); uc-486 checks the drawn step against it. */
  layoutHeight?: number;
  /** One or two lines for the title, as the layout counted them (layout/node-size.ts `titleLines`). */
  titleLines?: 1 | 2;
  /** On a run's canvas (c-097): what this node's step did; absent in the editor. */
  run?: RunMark;
};

/** A node's step in one run: passed, failed, skipped (the run ended without reaching it), or still in flight. */
export type RunMark = 'passed' | 'failed' | 'skipped' | 'stopped' | 'running' | 'waiting' | 'not_reached';

const RUN_MARK: Record<RunMark, { label: string; icon: typeof CheckCircle2; className: string; badge: string }> = {
  passed: { label: 'Passed', icon: CheckCircle2, className: 'border-success', badge: 'border-success/40 bg-success/10 text-success-text' },
  failed: { label: 'Failed', icon: XCircle, className: 'border-destructive border-2', badge: 'border-destructive/40 bg-destructive/10 text-destructive' },
  skipped: { label: 'Skipped', icon: CircleSlash, className: 'border-dashed opacity-60', badge: 'text-muted-foreground' },
  stopped: { label: 'Stopped', icon: CircleSlash, className: 'border-warning', badge: 'border-warning/40 bg-warning/10 text-warning-text' },
  running: { label: 'Running', icon: Loader2, className: 'border-primary', badge: 'text-primary' },
  waiting: { label: 'Waiting', icon: Clock, className: 'border-warning', badge: 'border-warning/40 bg-warning/10 text-warning-text' },
  not_reached: { label: 'Not reached yet', icon: CircleDashed, className: 'border-dashed', badge: 'text-muted-foreground' },
};

export type DefinitionFlowNode = Node<DefinitionNodeData, 'definition'>;

const GROUP: Record<string, { icon: LucideIcon; tile: string }> = {
  trigger: { icon: Zap, tile: 'bg-primary/10 text-primary' },
  data: { icon: Braces, tile: 'bg-chart-1/15 text-chart-1' },
  flow: { icon: GitBranch, tile: 'bg-muted text-muted-foreground' },
  action: { icon: Wrench, tile: 'bg-chart-3/15 text-chart-3' },
  ai: { icon: Sparkles, tile: 'bg-chart-2/15 text-chart-2' },
  human: { icon: UserCheck, tile: 'bg-warning/15 text-warning-text' },
};
const END = { icon: Flag, tile: 'bg-success/15 text-success-text' };
const UNKNOWN = { icon: HelpCircle, tile: 'bg-muted text-muted-foreground' };

/** The icon and tile colour of a step's group, shared by the canvas node and the step list. */
export function groupLook(group: string | null | undefined, typeId?: string): { icon: LucideIcon; tile: string } {
  if (typeId === 'ops.flow.end') return END;
  return (group && GROUP[group]) || UNKNOWN;
}

const HANDLE = '!size-2.5 !border-2 !border-background !bg-muted-foreground';

export const DefinitionNode = memo(function DefinitionNode({ data, selected }: NodeProps<DefinitionFlowNode>) {
  const rows = Math.max(data.inputs.length, data.outputs.length);
  const look = data.unknown ? UNKNOWN : groupLook(data.group, data.typeId);
  const Icon = look.icon;
  const trigger = data.group === 'trigger';
  const broken = data.hasError || data.unknown;
  return (
    <div
      data-testid="definition-node"
      data-node-id={data.nodeId}
      data-error={broken ? 'true' : undefined}
      data-run={data.run}
      data-layout-height={data.layoutHeight}
      className={cn(
        'relative w-72 rounded-xl border bg-card text-card-foreground shadow-sm transition-shadow hover:shadow-md',
        trigger && 'border-2 border-dashed border-primary/50',
        broken && 'border-2 border-destructive',
        data.run && RUN_MARK[data.run].className,
        data.run && data.run !== 'skipped' && data.run !== 'not_reached' && 'cursor-pointer',
        selected && 'ring-2 ring-primary ring-offset-2 ring-offset-background',
      )}
    >
      {data.run && <RunBadge mark={data.run} />}
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.tile)}>
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn('text-base font-medium', data.titleLines === 2 ? 'line-clamp-2 h-12' : 'truncate')} title={data.title} data-testid="node-title">
            {data.title}
          </p>
          <p className="truncate text-sm text-muted-foreground">{data.typeLabel}</p>
          {data.repeats && (
            <p className="flex items-center gap-1 truncate text-sm text-primary" data-testid="node-repeats" title={data.repeatsFull ?? data.repeats ?? undefined}>
              <Repeat className="size-3 shrink-0" aria-hidden /> {data.repeats}
            </p>
          )}
        </div>
        {data.unknown ? (
          <Badge variant="destructive" className="shrink-0">
            <HelpCircle /> Unknown type
          </Badge>
        ) : (
          (data.hasError && <AlertTriangle className="size-4 shrink-0 text-destructive" aria-label="Has an error" />) ||
          (data.hasWarning && <AlertTriangle className="size-4 shrink-0 text-warning-text" aria-label="Has a warning" data-testid="node-warning" />)
        )}
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
              <div key={i} className="relative flex min-h-5 items-center justify-between gap-2 px-3 text-sm">
                {input ? (
                  <>
                    <Handle type="target" position={Position.Left} id={input.name} data-port={input.name} className={HANDLE} />
                    <span className="min-w-0 truncate text-muted-foreground">{input.label}</span>
                  </>
                ) : (
                  <span />
                )}
                {output && (
                  <>
                    <span className="min-w-0 truncate text-right">{output.label}</span>
                    <Handle type="source" position={Position.Right} id={output.name} data-port={output.name} className={HANDLE} />
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

function RunBadge({ mark }: { mark: RunMark }) {
  const m = RUN_MARK[mark];
  const Icon = m.icon;
  return (
    // On the card's top edge rather than a row of its own: the step keeps the height the layout gave it, so a run's
    // marks never close the gap between two steps of a column that lines are routed through.
    <Badge variant="outline" className={cn('absolute -top-2.5 left-3 z-10 gap-1 bg-card font-normal', m.badge)} data-testid="run-mark">
      <Icon className={cn('size-3', mark === 'running' && 'animate-spin')} /> {m.label}
    </Badge>
  );
}

export const definitionNodeTypes = { definition: DefinitionNode };
