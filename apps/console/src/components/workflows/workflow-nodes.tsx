"use client"

import { memo } from "react"
import {
  type NodeTypes,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react"
import {
  Phone,
  CheckCircle,
  XCircle,
  GitBranch,
  Sparkles,
  Brain,
  UserCheck,
  ShieldCheck,
  Clock,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { ICONS, CAT_COLORS, type StepData } from "./node-types"

// ── Step Node ──

/** A check the service failed for this node, from the last validation. */
function NodeError({ data }: { data: StepData }) {
  if (typeof data.apiError !== "string") return null
  return (
    <p className="border-t border-destructive/40 bg-destructive/10 px-3 py-1.5 text-[10px] leading-snug text-destructive" role="alert" data-testid="node-error">
      {data.apiError}
    </p>
  )
}

export const StepNode = memo(function StepNode({ data, selected }: NodeProps & { data: StepData }) {
  const Icon = ICONS[data.icon] || Brain
  const c = CAT_COLORS[data.category] || CAT_COLORS.ai
  const isAI = data.category === "ai"
  const statusDot = data.status === "success" ? "bg-success"
    : data.status === "error" ? "bg-destructive"
    : data.status === "active" ? "bg-indigo-400 animate-pulse" : null

  return (
    <div className={cn(
      "rounded-xl border bg-card shadow-md w-52.5 transition-all",
      c.border,
      isAI && "border-2 shadow-lg",
      isAI && c.glow,
      selected && "ring-2 ring-primary",
    )}>
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />
      {isAI && (
        <div className="bg-indigo-500/10 px-3 py-1 rounded-t-xl border-b border-indigo-500/20 flex items-center gap-1.5">
          <Sparkles className="size-3 text-indigo-600 dark:text-indigo-400" />
          <span className="text-[9px] font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider">AI</span>
        </div>
      )}
      <div className="p-3">
        <div className="flex items-center gap-2.5">
          <div className={cn("flex size-8 items-center justify-center rounded-lg shrink-0", c.bg)}>
            <Icon className={cn("size-4", c.text)} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-foreground truncate">{data.label}</p>
              {statusDot && <span className={cn("size-1.5 rounded-full shrink-0", statusDot)} />}
            </div>
            <p className="text-[10px] text-muted-foreground truncate">{data.description}</p>
          </div>
        </div>
        {data.badge && (
          <div className="mt-2 flex">
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{data.badge}</span>
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-muted-foreground !w-2 !h-2" />
      <NodeError data={data} />
    </div>
  )
})

// ── Trigger Node ──

export const TriggerNode = memo(function TriggerNode({ data, selected }: NodeProps & { data: StepData }) {
  const Icon = ICONS[data.icon] || Phone
  return (
    <div className={cn(
      "rounded-xl border-2 border-dashed border-violet-500/40 bg-violet-500/5 w-52.5 transition-all",
      selected && "ring-2 ring-primary",
    )}>
      <div className="p-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-violet-500/20 shrink-0">
            <Icon className="size-4 text-violet-600 dark:text-violet-400" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium text-foreground truncate">{data.label}</p>
            <p className="text-[10px] text-muted-foreground truncate">{data.description}</p>
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-chart-3 !w-2 !h-2" />
    </div>
  )
})

// ── End Node ──

export const EndNode = memo(function EndNode({ data, selected }: NodeProps & { data: StepData }) {
  const isError = data.icon === "x"
  return (
    <div className={cn(
      "rounded-xl border-2 w-40 transition-all",
      isError ? "border-destructive/40 bg-destructive/5" : "border-success/40 bg-success/5",
      selected && "ring-2 ring-primary",
    )}>
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />
      <div className="p-3 flex items-center gap-2 justify-center">
        {isError ? <XCircle className="size-4 text-destructive" /> : <CheckCircle className="size-4 text-success-text" />}
        <p className="text-xs font-medium">{data.label}</p>
      </div>
    </div>
  )
})

// ── Router Node (AI decision point) ──

export const RouterNode = memo(function RouterNode({ data, selected }: NodeProps & { data: StepData }) {
  return (
    <div className={cn(
      "rounded-xl border-2 border-indigo-500/40 bg-card shadow-lg w-52.5 transition-all",
      "shadow-indigo-500/10",
      data.status === "active" && "border-indigo-500 ring-2 ring-indigo-500/30",
      data.status === "success" && "border-success/60",
      selected && "ring-2 ring-primary",
    )}>
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />
      <div className="bg-indigo-500/10 px-3 py-1 rounded-t-xl border-b border-indigo-500/20 flex items-center gap-1.5">
        <Sparkles className="size-3 text-indigo-600 dark:text-indigo-400" />
        <span className="text-[9px] font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider">AI Router</span>
      </div>
      <div className="p-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-indigo-500/20 shrink-0">
            <GitBranch className="size-4 text-indigo-600 dark:text-indigo-300" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium text-foreground truncate">{data.label}</p>
            <p className="text-[10px] text-muted-foreground truncate">{data.description}</p>
          </div>
        </div>
      </div>
      {/* Multiple outputs */}
      <Handle type="source" position={Position.Right} id="top" className="!bg-chart-2 !w-2 !h-2" style={{ top: '25%' }} />
      <Handle type="source" position={Position.Right} id="mid" className="!bg-warning !w-2 !h-2" style={{ top: '50%' }} />
      <Handle type="source" position={Position.Right} id="bot" className="!bg-chart-3 !w-2 !h-2" style={{ top: '75%' }} />
      <Handle type="source" position={Position.Bottom} id="fallback" className="!bg-muted-foreground !w-2 !h-2" />
      <NodeError data={data} />
    </div>
  )
})

// ── Review Node (human-in-the-loop gate) ──
// Three outputs: approved and rejected carry the reviewer's decision; timeout fires when the SLA lapses.

export const ReviewNode = memo(function ReviewNode({ data, selected }: NodeProps & { data: StepData }) {
  return (
    <div className={cn(
      "w-57.5 rounded-xl border-2 border-dashed border-warning/60 bg-card shadow-md transition-all",
      data.status === "active" && "border-solid border-warning shadow-lg shadow-warning/20",
      selected && "ring-2 ring-primary",
    )}>
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />
      <div className="flex items-center gap-1.5 rounded-t-xl border-b border-warning/40 bg-warning/10 px-3 py-1">
        <UserCheck className="size-3 text-warning-text" />
        <span className="text-[9px] font-semibold uppercase tracking-wider text-warning-text">Human review</span>
        {data.sla && (
          <span className="ml-auto flex items-center gap-1 text-[9px] text-warning-text">
            <Clock className="size-2.5" /> {data.sla}
          </span>
        )}
      </div>
      <div className="p-3">
        <p className="text-xs font-medium text-foreground">{data.label}</p>
        <p className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
          {data.reviewers}
          {data.fourEyes && <ShieldCheck className="size-3 text-primary" />}
        </p>
        {data.condition && (
          <code className="mt-2 block truncate rounded bg-muted px-1.5 py-1 font-mono text-[9.5px] text-muted-foreground">{data.condition}</code>
        )}
      </div>
      {data.status === "active" && (
        <div className="flex items-center gap-1.5 rounded-b-xl border-t border-warning/40 bg-warning/10 px-3 py-1.5 text-[10px] font-medium text-warning-text">
          <span className="size-1.5 animate-pulse rounded-full bg-warning" /> Waiting on reviewer
        </div>
      )}
      <Handle type="source" position={Position.Right} id="approved" className="!bg-success !w-2 !h-2" style={{ top: "30%" }} />
      <Handle type="source" position={Position.Right} id="rejected" className="!bg-destructive !w-2 !h-2" style={{ top: "62%" }} />
      <Handle type="source" position={Position.Bottom} id="timeout" className="!bg-muted-foreground !w-2 !h-2" />
      <NodeError data={data} />
    </div>
  )
})

// ── Branch Node (classify, condition, switch): one labelled output per branch ──

export const BranchNode = memo(function BranchNode({ data, selected }: NodeProps & { data: StepData }) {
  const Icon = ICONS[data.icon] || GitBranch
  const c = CAT_COLORS[data.category] || CAT_COLORS.logic
  const branches = (data.branches as string[] | undefined)?.length ? (data.branches as string[]) : ["Next"]
  return (
    <div className={cn("w-55 rounded-xl border-2 bg-card shadow-md transition-all", c.border, selected && "ring-2 ring-primary")}>
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />
      <div className="flex items-center gap-2.5 p-3">
        <div className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", c.bg)}>
          <Icon className={cn("size-4", c.text)} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-foreground">{data.label}</p>
          <p className="truncate text-[10px] text-muted-foreground">{data.description || "Not configured"}</p>
        </div>
      </div>
      <div className="flex flex-col border-t">
        {branches.map((b) => (
          <div key={b} className="relative flex h-6 items-center justify-end pr-3 text-[10px] text-muted-foreground">
            {b}
            <Handle type="source" position={Position.Right} id={b} className="!bg-muted-foreground !w-2 !h-2" style={{ top: "50%" }} />
          </div>
        ))}
      </div>
      <NodeError data={data} />
    </div>
  )
})

export const nodeTypes: NodeTypes = {
  branch: BranchNode,
  step: StepNode,
  trigger: TriggerNode,
  end: EndNode,
  router: RouterNode,
  review: ReviewNode,
}
