import { Bot, Route, Sparkles } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { AssetKind, AssetRef, AssuranceRunTrigger, CaseOutcome, GateStep } from '@/lib/types/assurance';

export const KIND_LABEL: Record<AssetKind, string> = { agent: 'Agent', skill: 'Skill', workflow: 'Workflow' };
export const KIND_ICON: Record<AssetKind, typeof Bot> = { agent: Bot, skill: Sparkles, workflow: Route };
export const KIND_OPTIONS = (Object.keys(KIND_LABEL) as AssetKind[]).map((k) => ({ value: k, label: KIND_LABEL[k], icon: KIND_ICON[k] }));

export const TRIGGER_LABEL: Record<AssuranceRunTrigger, string> = {
  publish_request: 'Publish request',
  model_update: 'Model update',
  manual: 'Manual',
  knowledge_change: 'Knowledge change',
  version_saved: 'Version saved',
};

export const TIER_OPTIONS = (['critical', 'high', 'medium', 'low'] as const).map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }));

/** Asset name with its kind, as the first cell of every Assurance table. */
export function AssetCell({ asset, sub }: { asset: AssetRef; sub?: string }) {
  const Icon = KIND_ICON[asset.kind];
  return (
    <div className="flex w-56 max-w-56 items-center gap-2.5" title={asset.name}>
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <div className="truncate font-medium">{asset.name}</div>
        <div className="truncate text-xs text-muted-foreground">{sub ?? KIND_LABEL[asset.kind]}</div>
      </div>
    </div>
  );
}

export function OutcomeText({ outcome }: { outcome: CaseOutcome | null }) {
  if (!outcome) return <span className="text-muted-foreground">—</span>;
  return <span className={cn('font-medium', outcome === 'pass' ? 'text-success-text' : 'text-destructive')}>{outcome === 'pass' ? 'Pass' : 'Fail'}</span>;
}

const STEP_TONE: Record<GateStep['result'], string> = {
  pass: 'border-success/40 bg-success/10 text-success-text',
  fail: 'border-destructive/30 bg-destructive/10 text-destructive',
  pending: 'border-border bg-muted text-muted-foreground',
};

/** One gate step as a compact chip: result colour, and a dashed border when the tier makes it advisory. */
export function GateStepChip({ step }: { step: GateStep }) {
  return (
    <span
      className={cn('inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] whitespace-nowrap', STEP_TONE[step.result], step.mode === 'advisory' && 'border-dashed')}
      title={`${step.label} · ${step.mode === 'advisory' ? 'Advisory' : 'Blocking'} · ${step.detail}`}
    >
      {step.label}
    </span>
  );
}
